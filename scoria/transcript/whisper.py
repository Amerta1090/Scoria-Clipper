"""whisper-cli bridge: deterministic invocation, JSON parse, manifest tool info.

Format reality (ADR-013): whisper.cpp >= 1.9 no longer writes a `words` array. With
`-ojf` it emits per-token `t_dtw` centisecond timestamps, and only when flash-attn
is off AND `--dtw <preset>` is passed. Word spans here are therefore reconstructed
from contiguous BPE tokens — `word.end` is the last token's start tick (the raw
data carries no token end); sentence grouping absorbs the approximation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from scoria.audio.extract import extract_pcm
from scoria.config.schema import TranscriptConfig
from scoria.errors import MissingDependencyError, PipelineError, TranscriptError
from scoria.project.jsonio import read_json
from scoria.transcript.models import DTW_TICK_SECONDS, Word
from scoria.util.hash import sha256_file
from scoria.util.process import run_tool
from scoria.util.wav import write_wav_f32

# whisper's native input rate; the bridge resamples to 16 kHz mono f32 (same PCM
# the audio stage already uses).
_WHISPER_RATE = 16000

# `--dtw` accepts an attention-heads preset per model size; the multilingual and
# `.en` variants differ, so match the longest flag first against the model filename.
_DTW_PRESETS = (
    "tiny.en",
    "tiny",
    "base.en",
    "base",
    "small.en",
    "small",
    "medium.en",
    "medium",
)

_VERSION_TIMEOUT = 30


def _find_binary(binary: str) -> str:
    """Resolve an absolute/relative binary path or a PATH lookup; missing -> exit 1."""
    if os.sep in binary:
        path = Path(binary).expanduser()
        if path.is_file():
            return str(path)
        raise MissingDependencyError(f"whisper binary not found: {binary}")
    from shutil import which

    path = which(binary)
    if path is None:
        raise MissingDependencyError(f"{binary} not found on PATH")
    return path


def resolve_transcript_paths(tc: TranscriptConfig) -> tuple[str, Path]:
    """Return (resolved binary, resolved model path). Model is CWD-relative when relative."""
    binary = _find_binary(tc.binary)
    return binary, resolve_model_path(tc)


def resolve_model_path(tc: TranscriptConfig) -> Path:
    """Resolve the configured model path (CWD-relative when relative)."""
    model = Path(tc.model).expanduser()
    if not model.is_absolute():
        model = Path.cwd() / model
    return model


def _dtw_preset(model: Path) -> str | None:
    base = model.name.lower()
    for preset in _DTW_PRESETS:
        if preset in base:
            return preset
    return None


def _is_special_token(text: str) -> bool:
    return text.startswith("[") and text.endswith("]")


def _merge_word(pieces: list[tuple[str, float]]) -> Word:
    text = "".join(piece for piece, _ in pieces).strip()
    return Word(text=text, start=pieces[0][1], end=pieces[-1][1])


def _words_from_tokens(segment: dict[str, Any]) -> list[Word]:
    words: list[Word] = []
    pieces: list[tuple[str, float]] = []
    for token in segment.get("tokens", []):
        text = token.get("text", "")
        tick = token.get("t_dtw", -1)
        if not text or _is_special_token(text) or not isinstance(tick, (int, float)) or tick < 0:
            continue
        seconds = tick * DTW_TICK_SECONDS
        if pieces and not text.startswith(" "):
            pieces.append((text, seconds))
        else:
            if pieces:
                words.append(_merge_word(pieces))
            pieces = [(text, seconds)]
    if pieces:
        words.append(_merge_word(pieces))
    return words


def parse_whisper(raw: dict[str, Any]) -> tuple[str | None, list[Word], list[int]]:
    """Extract (language, flat words, per-segment last-word indices) from whisper JSON.

    `segment_end_indices` are positions into the returned word list marking each
    non-empty whisper segment's final word — the sentence grouping hint (ADR-013).
    """
    result = raw.get("result") or {}
    language = result.get("language")
    words: list[Word] = []
    segment_end_indices: list[int] = []
    for segment in raw.get("transcription", []):
        segment_words = _words_from_tokens(segment)
        if segment_words:
            segment_end_indices.append(len(words) + len(segment_words) - 1)
            words.extend(segment_words)
    return language, words, segment_end_indices


def run_whisper(
    input_path: Path,
    *,
    config,
    temp_dir: Path,
) -> dict[str, Any]:
    """Decode, run whisper-cli with the pinned arg surface, and parse its JSON."""
    tc = config.transcript
    _, model = resolve_transcript_paths(tc)
    if not model.is_file():
        raise TranscriptError(
            f"whisper model not found: {model}",
            hint=f"run `clipper fetch-model --output {model}` to download it",
        )
    if tc.model_sha256:
        actual = sha256_file(model)
        if actual != tc.model_sha256:
            raise TranscriptError(
                f"whisper model {model} sha256 mismatch "
                f"(got {actual[:12]}, expected {tc.model_sha256[:12]})",
                hint="re-download the model, or update transcript.model_sha256",
            )
    preset = _dtw_preset(model)
    if preset is None:
        raise TranscriptError(
            f"cannot infer a `--dtw` preset for model {model.name}; "
            f"expected one of: {', '.join(_DTW_PRESETS)}",
            hint="use a tiny/base/small/medium ggml model (MVP; large has no aheads preset)",
        )
    samples = extract_pcm(input_path, rate=_WHISPER_RATE)
    wav = Path(temp_dir) / f"{Path(input_path).stem}-whisper.wav"
    json_path = Path(f"{wav}.json")
    write_wav_f32(wav, samples, rate=_WHISPER_RATE)
    args = [
        "-m",
        str(model),
        "-f",
        str(wav),
        "-l",
        tc.language or "auto",
        "-t",
        str(tc.threads),
        "-bs",
        "0",
        "-nt",
        "-np",
        "-sow",
        "-nfa",
        "-dtw",
        preset,
        "-ojf",
    ]
    try:
        run_tool(resolve_transcript_paths(tc)[0], args)
        if not json_path.is_file():
            raise TranscriptError(
                f"whisper-cli exited 0 but wrote no JSON at {json_path}",
                hint="check the whisper-cli build; the bridge expects `-ojf` output",
            )
        return read_json(json_path)
    except PipelineError as exc:
        if isinstance(exc, TranscriptError):
            raise
        raise TranscriptError(str(exc), hint=exc.hint) from exc
    finally:
        if not config.project.keep_temp:
            wav.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)


def whisper_cli_info(tc: TranscriptConfig) -> dict[str, str] | None:
    """Manifest stamp: {'binary', 'version'} or None when the binary is absent."""
    try:
        binary = _find_binary(tc.binary)
    except MissingDependencyError:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=_VERSION_TIMEOUT
        )
        first = (proc.stdout or "").splitlines()[0] if proc.returncode == 0 else ""
    except OSError:
        return None
    if not first:
        return None
    return {"binary": binary, "version": first}


def whisper_model_info(tc: TranscriptConfig) -> dict[str, str]:
    """Manifest stamp: resolved model path + sha256 (empty when the file is absent)."""
    model = resolve_model_path(tc)
    return {"path": str(model), "sha256": sha256_file(model) if model.is_file() else ""}
