"""Report-stage output models: the `previews.json` document (Sprint 10).

`clipper report` / `clipper preview` turn existing JSON artifacts (`analysis.json`
+ `ranking.json`) plus the source video into debugging assets: a still thumbnail
per selected clip, a contact sheet per clip, and a timeline strip. No analysis is
rerun (ARCHITECTURE.md §9): timings come from ranking.json and geometry from
`analysis.media`. Every float is normalized to the 4-decimal serialization
contract (ADR-010) on write.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PREVIEWS_SCHEMA = "previews"
PREVIEWS_VERSION = 1

# Stamped on the document — the deterministic record of *how* the still assets
# were sampled (mirrors RANK_VERSION / FUNCTION_IDS style).
PREVIEW_VERSION = "still.mid.v1"


class ClipPreview(BaseModel):
    """One selected clip's preview assets (paths are project-dir relative)."""

    id: str
    rank: int
    start: float
    end: float
    duration: float
    mid: float
    thumbnail: str
    contact_sheet: str
    strip_times: list[float]


class TimelineAsset(BaseModel):
    file: str
    width: int
    height: int
    media_duration: float


class PreviewsInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["previews"] = Field(PREVIEWS_SCHEMA, alias="schema")
    version: int = PREVIEWS_VERSION
    preview_version: str = PREVIEW_VERSION
    input: str
    source: str
    media_duration: float
    preview_width: int
    samples_per_clip: int
    image_format: str = "png"
    clips: list[ClipPreview]
    timeline: TimelineAsset
