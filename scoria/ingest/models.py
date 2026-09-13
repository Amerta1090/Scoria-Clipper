"""Typed ingest output: the `media` section of analysis.json (ARCHITECTURE.md §6).

All timestamps are normalized to **seconds** at ingest (SPRINT_PLANNING.md §Sprint 1
risk): `duration`/`start_time` are floats in seconds, `time_base` is kept as the raw
rational string from ffprobe for diagnostics/manifest only — never used as a basis for
later math. Floats are rounded to 4 decimals by the serialization contract on write.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ANALYSIS_SCHEMA = "analysis"
MEDIA_SCHEMA = "media-info"

FILE_SOURCE = "file"
STDIN_SOURCE = "stdin"


class AnalysisWindow(BaseModel):
    """The [start, end) seconds that downstream stages actually analyze."""

    start: float
    end: float


class MediaInfo(BaseModel):
    """`schema` is emitted as the `schema` key but stored as `document_schema` to
    avoid shadowing pydantic's `BaseModel.schema`."""

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["media-info"] = Field(MEDIA_SCHEMA, alias="schema")
    source: str
    source_kind: Literal["file", "stdin"]
    container: str
    stream_index: int
    codec: str | None
    width: int
    height: int
    pixel_format: str | None
    duration: float
    start_time: float
    time_base: str | None
    avg_frame_rate: str | None
    frame_count: int | None
    aspect_ratio: float
    display_aspect_ratio: str | None
    rotation: float
    analysis: AnalysisWindow
