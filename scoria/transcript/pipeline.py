"""The transcript stage: input file → `analysis.json.transcript` (ARCHITECTURE.md §5.3).

Deterministic decode + whisper run → parsed words → normalization → sentence
grouping with inferred punctuation. Degradation: when `transcript.enabled` is false
(flag or config) the stage emits `transcript: null` and reports `["transcript"]` as
a degraded flag; runtime STT failures raise (exit 1) per CLI_SPEC §6 — degraded
paths are only ever entered through the explicit flag.
"""

from __future__ import annotations

from pathlib import Path

from scoria.config.schema import ScoriaConfig
from scoria.transcript.core import group_sentences, normalize_words
from scoria.transcript.models import TRANSCRIPT_SCHEMA, TranscriptInfo
from scoria.transcript.whisper import parse_whisper, run_whisper
from scoria.util.logging import get_logger

logger = get_logger("transcript")

TRANSCRIPT_ENGINE = "whisper.cpp"


def analyze_transcript(
    input_path: Path,
    config: ScoriaConfig,
    *,
    temp_dir: Path,
) -> tuple[TranscriptInfo | None, list[str]]:
    """Return (transcript contract | None, degraded-flag list). Raises on STT failure."""
    if not config.transcript.enabled:
        return None, ["transcript"]
    raw = run_whisper(input_path, config=config, temp_dir=temp_dir)
    language, words, segment_end_indices = parse_whisper(raw)
    words = normalize_words(words)
    if not words:
        logger.warning(
            "whisper produced no words for '%s'; emitting transcript: null",
            input_path.name,
            extra={"stage": "transcript"},
        )
        return None, ["transcript"]
    sentences = group_sentences(
        words,
        max_gap_seconds=config.transcript.sentence.max_gap_seconds,
        min_sentence_words=config.transcript.sentence.min_sentence_words,
        force_punctuation=config.transcript.sentence.force_punctuation,
        segment_end_indices=segment_end_indices if config.transcript.segment_from_whisper else (),
    )
    info = TranscriptInfo(
        schema=TRANSCRIPT_SCHEMA,
        engine=TRANSCRIPT_ENGINE,
        language=language,
        model=config.transcript.model,
        model_sha256=config.transcript.model_sha256,
        greedy=config.transcript.greedy,
        threads=config.transcript.threads,
        words=words,
        sentences=sentences,
        word_count=len(words),
        sentence_count=len(sentences),
    )
    return info, []
