"""`transcript.path` ingest (ADR-021): load + contract-validate a saved transcript-info document.

When a run is pointed at a saved `transcript-info` JSON instead of an STT binary, the
stage must be every bit as strict as the whisper path: a broken doc is a **hard error**
(exit 1), never a silent skip. Validation is deliberately narrow and matches the ADR:
schema match, non-empty `words`, every word a real span, and strictly monotonic
(non-overlapping) timestamps. Words then flow through the exact same
`normalize_words` → `group_sentences` path as whisper output, so a file-fed run is
byte-equivalent to a whisper-fed run for identical words — with the whisper segment
hints (`segment_end_indices`) preserved in the document for identical grouping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scoria.errors import TranscriptError
from scoria.project.jsonio import read_json
from scoria.transcript.core import normalize_words
from scoria.transcript.models import TRANSCRIPT_SCHEMA, TRANSCRIPT_SOURCE_WHISPER, Word


@dataclass(frozen=True)
class LoadedTranscript:
    """A validated transcript-info document, ready for sentence grouping."""

    engine: str
    language: str | None
    model: str
    model_sha256: str
    greedy: bool
    threads: int
    words: list[Word]
    segment_end_indices: list[int]


def _resolve(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_text(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def load_transcript_doc(path: str) -> LoadedTranscript:
    """Load + validate `path` (a saved transcript-info document).

    Raises `TranscriptError` (exit 1) for anything that cannot be a transcript:
    missing file, invalid JSON, wrong schema, missing/empty words, malformed word
    spans, or non-monotonic timestamps. Never returns a degraded result.
    """
    doc_path = _resolve(path)
    if not doc_path.is_file():
        raise TranscriptError(
            f"transcript.path file not found: {doc_path}",
            hint="point transcript.path at a saved transcript-info JSON document (schema + words)",
        )
    try:
        raw = read_json(doc_path)
    except Exception as exc:  # read_json raises PipelineError for IO / bad JSON
        raise TranscriptError(
            f"cannot read transcript.path document {doc_path}: {exc}",
            hint="the file must be valid JSON (a saved transcript-info document)",
        ) from exc

    if not isinstance(raw, dict):
        raise TranscriptError(
            f"transcript.path document is not a JSON object: {doc_path}",
            hint="a transcript-info document is a JSON object with schema, words, sentences",
        )
    schema = raw.get("schema")
    if schema != TRANSCRIPT_SCHEMA:
        raise TranscriptError(
            f"transcript.path schema mismatch in {doc_path}: expected {TRANSCRIPT_SCHEMA!r}, "
            f"got {schema!r}",
            hint=f"point transcript.path at a saved transcript-info document "
            f"(schema == {TRANSCRIPT_SCHEMA!r}); extract the analysis.json.transcript section",
        )

    words_raw = raw.get("words")
    if not isinstance(words_raw, list) or not words_raw:
        raise TranscriptError(
            f"transcript.path document has no words (empty or missing 'words'): {doc_path}",
            hint="transcript-info must carry at least one word with start/end timestamps",
        )

    words: list[Word] = []
    for index, entry in enumerate(words_raw):
        prefix = f"transcript.path word #{index} in {doc_path}"
        if not isinstance(entry, dict):
            raise TranscriptError(
                f"{prefix} is not an object",
                hint="each word is {text, start, end} with numeric, non-negative timestamps",
            )
        text, start, end = entry.get("text"), entry.get("start"), entry.get("end")
        if not (isinstance(text, str) and _is_number(start) and _is_number(end)):
            raise TranscriptError(
                f"{prefix} needs text/start/end timestamps (got text={text!r} start={start!r} "
                f"end={end!r})",
                hint="each word is {text, start, end} with numeric timestamps in seconds",
            )
        if start < 0 or end < start:
            raise TranscriptError(
                f"{prefix} has an invalid span {start}..{end} (need 0 ≤ start ≤ end)",
                hint="timestamps are seconds; a word span may be zero-width (single token)",
            )
        if words and start < words[-1].end:
            raise TranscriptError(
                f"{prefix} starts at {start}, before the previous word's end "
                f"({words[-1].end}) — timestamps must be monotonic (no overlap)",
                hint="sort and de-overlap the words, or re-save the transcript-info document",
            )
        words.append(Word(text=text, start=float(start), end=float(end)))

    if not normalize_words(words):
        raise TranscriptError(
            f"transcript.path document yields no usable words after normalization: {doc_path}",
            hint="non-empty word entries must survive whitespace stripping",
        )

    # Per-segment sentence hints (ADR-013) are copied from the document so a
    # file-fed run groups sentences exactly like the whisper run that saved it.
    indices_raw = raw.get("segment_end_indices", [])
    if not isinstance(indices_raw, list) or not all(
        _is_number(i) and i == int(i) and 0 <= int(i) < len(words) for i in indices_raw
    ):
        raise TranscriptError(
            f"transcript.path segment_end_indices are invalid in {doc_path}",
            hint="segment_end_indices must be word-list indices in 0..len(words)-1",
        )
    indices = [int(i) for i in indices_raw]
    if any(a >= b for a, b in zip(indices, indices[1:], strict=False)):
        raise TranscriptError(
            f"transcript.path segment_end_indices are not strictly increasing in {doc_path}",
            hint="segment_end_indices must list progressively later word indices",
        )

    # Provenance fields come from the document itself (that is what produced the
    # words); word_count/sentence_count are recomputed after grouping.
    return LoadedTranscript(
        engine=_as_text(raw.get("engine"), TRANSCRIPT_SOURCE_WHISPER),
        language=raw.get("language") if isinstance(raw.get("language"), str) else None,
        model=_as_text(raw.get("model"), ""),
        model_sha256=_as_text(raw.get("model_sha256"), ""),
        greedy=bool(raw.get("greedy", True)),
        threads=raw.get("threads") if isinstance(raw.get("threads"), int) else 4,
        words=words,
        segment_end_indices=indices,
    )
