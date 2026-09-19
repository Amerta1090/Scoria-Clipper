"""The transcript stage: input file → `analysis.json.transcript` (ARCHITECTURE.md §5.3).

Deterministic decode + whisper run → parsed words → normalization → sentence
grouping with inferred punctuation. Degradation: when `transcript.enabled` is false
(flag or config) the stage emits `transcript: null` and reports `["transcript"]` as
a degraded flag; runtime STT failures raise (exit 1) per CLI_SPEC §6 — degraded
paths are only ever entered through the explicit flag.

Offline ingest (ADR-021): when `transcript.path` is set (with `transcript.enabled:
true`) the stage loads + contract-validates a saved `transcript-info` document
instead of running whisper.cpp — deterministic, no STT binary, CI-safe. Words flow
through the same normalization + sentence grouping as the whisper path, so a
file-fed run is byte-equivalent to a whisper-fed run for identical words.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scoria.config.schema import ScoriaConfig
from scoria.errors import TranscriptError
from scoria.transcript.core import group_sentences, normalize_words
from scoria.transcript.file import LoadedTranscript, load_transcript_doc
from scoria.transcript.models import TRANSCRIPT_SCHEMA, TranscriptInfo
from scoria.transcript.whisper import parse_whisper, run_whisper
from scoria.util.logging import get_logger

logger = get_logger("transcript")

TRANSCRIPT_ENGINE = "whisper.cpp"


@dataclass(frozen=True)
class _WordSource:
    """Normalized word list + whisper segment hints (ADR-013) before grouping."""

    language: str | None
    words: list
    segment_end_indices: list[int]


def analyze_transcript(
    input_path: Path,
    config: ScoriaConfig,
    *,
    temp_dir: Path,
) -> tuple[TranscriptInfo | None, list[str]]:
    """Return (transcript contract | None, degraded-flag list). Raises on STT failure."""
    if not config.transcript.enabled:
        return None, ["transcript"]
    if config.transcript.path:
        # ADR-021: a broken saved doc raises (exit 1), never a silent skip.
        loaded = load_transcript_doc(config.transcript.path)
        source = _WordSource(
            language=loaded.language,
            words=loaded.words,
            segment_end_indices=loaded.segment_end_indices,
        )
        info = _build_info(config, source, provenance=_provenance_of(loaded))
        if info is None:  # unreachable: the loader already rejects empty word lists
            raise TranscriptError(
                f"transcript.path document yields no words: {config.transcript.path}",
                hint="the saved transcript-info document must carry word timestamps",
            )
        return info, []
    raw = run_whisper(input_path, config=config, temp_dir=temp_dir)
    language, words, segment_end_indices = parse_whisper(raw)
    info = _build_info(
        config,
        _WordSource(language=language, words=words, segment_end_indices=segment_end_indices),
        provenance={
            "engine": TRANSCRIPT_ENGINE,
            "language": language,
            "model": config.transcript.model,
            "model_sha256": config.transcript.model_sha256,
            "greedy": config.transcript.greedy,
            "threads": config.transcript.threads,
        },
    )
    if info is None:
        logger.warning(
            "whisper produced no words for '%s'; emitting transcript: null",
            input_path.name,
            extra={"stage": "transcript"},
        )
        return None, ["transcript"]
    return info, []


def _provenance_of(loaded: LoadedTranscript) -> dict:
    """Provenance fields copied from the saved document (what produced the words)."""
    return {
        "engine": loaded.engine,
        "language": loaded.language,
        "model": loaded.model,
        "model_sha256": loaded.model_sha256,
        "greedy": loaded.greedy,
        "threads": loaded.threads,
    }


def _build_info(
    config: ScoriaConfig,
    source: _WordSource,
    *,
    provenance: dict,
) -> TranscriptInfo | None:
    words = normalize_words(source.words)
    if not words:
        return None
    sentences = group_sentences(
        words,
        max_gap_seconds=config.transcript.sentence.max_gap_seconds,
        min_sentence_words=config.transcript.sentence.min_sentence_words,
        force_punctuation=config.transcript.sentence.force_punctuation,
        segment_end_indices=source.segment_end_indices
        if config.transcript.segment_from_whisper
        else (),
    )
    return TranscriptInfo(
        schema=TRANSCRIPT_SCHEMA,
        engine=provenance["engine"],
        language=provenance["language"],
        model=provenance["model"],
        model_sha256=provenance["model_sha256"],
        greedy=provenance["greedy"],
        threads=provenance["threads"],
        words=words,
        sentences=sentences,
        word_count=len(words),
        sentence_count=len(sentences),
        segment_end_indices=list(source.segment_end_indices)
        if config.transcript.segment_from_whisper
        else [],
    )
