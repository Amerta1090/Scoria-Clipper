r"""Typed captions artifacts: words → lines → captions.json blocks (Sprint 7).

Each `Caption` is one on-screen block (an SRT cue / ASS dialogue line): a
time-bounded group of ≤ `max_lines` lines, every line ≤ `chars_per_line`
chars, block span ≤ `max_duration`, carrying the word timestamps (already
clamped to the clip window) so the ASS word-karaoke `\k` values and the
parse-back tests can derive exact spans. Times are seconds; floats are rounded
by the serialization contract on write (ADR-010).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scoria.transcript.models import Word

CAPTIONS_SCHEMA = "captions"
CAPTIONS_VERSION = 1
CAPTION_VERSION = "words_lines.v1"


class Caption(BaseModel):
    """One on-screen caption block (SRT cue / ASS dialogue line)."""

    start: float
    end: float
    lines: list[str]
    words: list[Word] = Field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.words)


class ClipCaptions(BaseModel):
    """All caption blocks for one selected clip."""

    id: str
    rank: int
    start: float
    end: float
    captions: list[Caption] = Field(default_factory=list)


class CaptionsInfo(BaseModel):
    """captions.json contract: selected clips → word-timed caption blocks."""

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["captions"] = Field(CAPTIONS_SCHEMA, alias="schema")
    version: int = CAPTIONS_VERSION
    caption_version: str = CAPTION_VERSION
    max_duration: float
    chars_per_line: int
    max_lines: int
    min_word_count: int
    clips: list[ClipCaptions]
