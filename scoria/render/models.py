"""Typed render summary (render.json) + version constants (Sprint 9).

`render/` never re-analyzes the source: every filter parameter derives from
ranking.json / analysis.json / reframe.json and the caption sidecars
(ARCHITECTURE.md §9 — render-without-reanalyze). The render.json summary records
the deterministic per-clip ffmpeg surface (filters string, static gain, burn
state, outcome) plus degradation flags; manifest.json stamps tool versions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RENDER_SCHEMA = "render"
RENDER_VERSION = 1
RENDER_PLAN_VERSION = "x264.v1"


class VideoSettings(BaseModel):
    """Effective video encode surface recorded in render.json."""

    codec: str
    crf: int
    preset: str
    pix_fmt: str
    faststart: bool


class AudioSettings(BaseModel):
    """Effective audio surface recorded in render.json."""

    codec: str
    method: str
    target_lufs: float
    target_peak: float
    lra: float


class ClipRenderResult(BaseModel):
    """One selected clip's render record (id-keyed, so rank-independent)."""

    id: str
    rank: int
    start: float
    end: float
    duration: float
    status: Literal["rendered", "exists", "skipped"]
    output_file: str
    filters: str | None = None
    gain_db: float = 0.0
    burned: bool = False


class RenderDoc(BaseModel):
    """render.json contract: whole-run summary with one entry per clip."""

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["render"] = Field(RENDER_SCHEMA, alias="schema")
    version: int = RENDER_VERSION
    render_version: str = RENDER_PLAN_VERSION
    input: str
    output: str
    threads: int
    video: VideoSettings
    audio: AudioSettings
    burn: bool
    degraded: list[str]
    deterministic: bool = True
    clips: list[ClipRenderResult]
