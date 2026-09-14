"""Transcript: whisper.cpp bridge, word spans, sentence grouping (Sprint 3)."""

from scoria.transcript.core import (
    DEFAULT_QUESTION_STARTERS,
    SEGMENT_BREAK_MIN_GAP_S,
    group_sentences,
    normalize_words,
)
from scoria.transcript.models import (
    DTW_TICK_SECONDS,
    TRANSCRIPT_SCHEMA,
    Sentence,
    TranscriptInfo,
    Word,
)
from scoria.transcript.pipeline import TRANSCRIPT_ENGINE, analyze_transcript
from scoria.transcript.whisper import (
    parse_whisper,
    resolve_model_path,
    run_whisper,
    whisper_cli_info,
    whisper_model_info,
)

__all__ = [
    "DEFAULT_QUESTION_STARTERS",
    "DTW_TICK_SECONDS",
    "SEGMENT_BREAK_MIN_GAP_S",
    "TRANSCRIPT_ENGINE",
    "TRANSCRIPT_SCHEMA",
    "Sentence",
    "TranscriptInfo",
    "Word",
    "analyze_transcript",
    "group_sentences",
    "normalize_words",
    "parse_whisper",
    "resolve_model_path",
    "run_whisper",
    "whisper_cli_info",
    "whisper_model_info",
]
