"""Typed reframe artifact: media AR → 9:16 crop/blur-pad plan (Sprint 8) or
two-zone gamer stack (Sprint 12).

One `ReframePlan` describes how to turn the *full source frame* into the
vertical `reframe.output` canvas. `layout: center` keeps the Sprint 8 contract —
a source-space center crop scaled down, a pure scale (source already 9:16), or a
blur-pad (contain-scaled content + blurred bars) — keyed by `strategy`. `layout:
gamer` (mode: gamer) instead carries `zones`: gameplay top (center-anchored
cover-fit crop → scale) + facecam PiP bottom (configured normalized region,
cover-fitted inside it), composited with `split` + `vstack` by `render/`.
Geometry is closed-form and deterministic — no RNG, no smoothing (ARCHITECTURE.md
§7/§9). `render/` (Sprint 9/12) turns the plan into the ffmpeg filter graph;
`reframe/` only does math. Floats are rounded to 4 decimals by the serialization
contract on write (ADR-010).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REFRAME_SCHEMA = "reframe"
REFRAME_VERSION = 2
REFRAME_PLAN_VERSION = "plan.v2"

Strategy = Literal["crop", "scale", "blur_pad"]
Layout = Literal["center", "gamer"]


class CropRect(BaseModel):
    """Source-space crop window (center/gamer modes); width/height/offsets are even (chroma)."""

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


class GamerZone(BaseModel):
    """One zone of the vertical stack: source crop window + canvas rect (Sprint 12).

    `crop` is the even, in-bounds source-space window that feeds the zone; after a
    `scale` to `width`×`height` it is placed at canvas offset `(x, y)`. v1 lenses:
    both zones are `x=0`, full canvas width, and their heights sum exactly to the
    canvas (`gameplay` on top, `facecam` below — no overlap, no gap).
    """

    role: Literal["gameplay", "facecam"]
    crop: CropRect
    x: int
    y: int
    width: int
    height: int


class ReframePlan(BaseModel):
    """reframe.json contract v2: one deterministic plan for the whole source video.

    `layout` selects how the canvas is built:
    - `center` → `strategy` picks which geometry is populated:
      - `crop`     → `crop` (source-space window), then scale to `output`
      - `scale`    → no geometry (output is a direct scale of the source)
      - `blur_pad` → `content` (contain dims) + `pad` (bar sizes in output px)
    - `gamer`    → `zones` (gameplay + facecam vertical stack); `strategy` is null
    """

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["reframe"] = Field(REFRAME_SCHEMA, alias="schema")
    version: int = REFRAME_VERSION
    reframe_version: str = REFRAME_PLAN_VERSION
    mode: Literal["center", "gamer", "faces", "target"] = "center"
    layout: Layout = "center"
    strategy: Strategy | None = None
    source: SourceGeometry
    output: OutputGeometry
    crop: CropRect | None = None
    content: ContentDims | None = None
    pad: PadBars | None = None
    zones: list[GamerZone] | None = None
