"""Typed reframe artifact: media AR → 9:16 crop/blur-pad plan (Sprint 8).

One `ReframePlan` describes how to turn the *full source frame* into the
vertical `reframe.output` canvas: either a source-space center crop that is
then scaled, a pure scale (source already 9:16), or a blur-pad (contain-scaled
content + blurred bars). Geometry is closed-form and deterministic — no RNG, no
smoothing (center mode, ARCHITECTURE.md §7/§9). `render/` (Sprint 9) turns the
plan into the ffmpeg filter graph; `reframe/` only does math. Floats are
rounded to 4 decimals by the serialization contract on write (ADR-010).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REFRAME_SCHEMA = "reframe"
REFRAME_VERSION = 1
REFRAME_PLAN_VERSION = "center.v1"

Strategy = Literal["crop", "scale", "blur_pad"]


class CropRect(BaseModel):
    """Source-space crop window (center mode); width/height/offsets are even (chroma)."""

    x: int
    y: int
    width: int
    height: int


class ContentDims(BaseModel):
    """Contain-scaled content size (blur-pad) before the bars are added."""

    width: int
    height: int


class PadBars(BaseModel):
    """Blur-pad bar sizes in output pixels; exactly two of the four are non-zero."""

    top: int
    bottom: int
    left: int
    right: int


class SourceGeometry(BaseModel):
    """Input frame: pixel dims + w/h aspect (rounded to the 4-decimal contract)."""

    width: int
    height: int
    aspect_ratio: float


class OutputGeometry(BaseModel):
    """Target canvas (`reframe.output`, validated even + exactly 9:16)."""

    width: int
    height: int


class ReframePlan(BaseModel):
    """reframe.json contract: one deterministic plan for the whole source video.

    `strategy` picks which geometry is populated:
    - `crop`     → `crop` (source-space window), then scale to `output`
    - `scale`    → no geometry (output is a direct scale of the source)
    - `blur_pad` → `content` (contain dims) + `pad` (bar sizes in output px)
    """

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["reframe"] = Field(REFRAME_SCHEMA, alias="schema")
    version: int = REFRAME_VERSION
    reframe_version: str = REFRAME_PLAN_VERSION
    mode: Literal["center", "faces", "target"] = "center"
    strategy: Strategy
    source: SourceGeometry
    output: OutputGeometry
    crop: CropRect | None = None
    content: ContentDims | None = None
    pad: PadBars | None = None
