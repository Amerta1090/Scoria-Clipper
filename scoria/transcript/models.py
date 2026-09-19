"""Typed transcript output: the `transcript` section of analysis.json.

Whisper.cpp v1.9.4 emits word timestamps as per-token `t_dtw` values (ADR-013);
this module groups contiguous BPE tokens into words, snaps overlaps away
(monotonic), and groups words into sentences with inferred punctuation. All
timestamps are seconds; floats are rounded by the serialization contract on write.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TRANSCRIPT_SCHEMA = "transcript-info"

# Runtime engine provenance for `manifest.json.transcript_source` (ADR-021):
# a run either invoked whisper.cpp or loaded a saved transcript-info doc.
TRANSCRIPT_SOURCE_WHISPER = "whisper.cpp"
TRANSCRIPT_SOURCE_FILE = "file"

# whisper.cpp's raw time unit in the JSON: 1 `t_dtw` tick == 10 ms.
DTW_TICK_SECONDS = 0.01


class Word(BaseModel):
    text: str
    start: float
    end: float


class Sentence(BaseModel):
    text: str
    start: float
    end: float
    words: list[Word]


class TranscriptInfo(BaseModel):
    """Transcript contract: flat word list + grouped sentences with punctuation."""

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["transcript-info"] = Field(TRANSCRIPT_SCHEMA, alias="schema")
    engine: str
    language: str | None
    model: str
    model_sha256: str
    greedy: bool
    threads: int
    words: list[Word]
    sentences: list[Sentence]
    word_count: int
    sentence_count: int
    # Per-segment last-word indices from whisper.cpp (ADR-013) — the sentence
    # grouping hints. Recorded in the doc so `transcript.path` ingest can
    # reproduce the identical grouping without running whisper (ADR-021).
    segment_end_indices: list[int] = Field(default_factory=list)
