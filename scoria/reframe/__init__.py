"""Reframe: AR → 9:16 crop/blur-pad plan + two-zone gamer stack (Sprint 8/12).

`build_reframe_plan` is the entry point: media (analysis.json) + config → the
`reframe.json` document that `render/` (Sprint 9/12) turns into an ffmpeg filter
graph. Center mode is deterministic by construction — no RNG, no smoothing
(ARCHITECTURE.md §7/§9); mode `gamer` builds the two-zone vertical stack
(`zones`); post-MVP `faces`/`target` modes live behind the same interface.
"""

from scoria.reframe.core import (
    REFRAME_PLAN_VERSION,
    REFRAME_SCHEMA,
    REFRAME_VERSION,
    build_reframe_plan,
    plan_for_dims,
)
from scoria.reframe.geometry import (
    compute_blur_pad,
    compute_crop,
    compute_gamer_zones,
    cover_crop,
    round_even,
    strategy_for,
)
from scoria.reframe.models import (
    ContentDims,
    CropRect,
    GamerZone,
    Layout,
    OutputGeometry,
    PadBars,
    ReframePlan,
    SourceGeometry,
)

__all__ = [
    "REFRAME_PLAN_VERSION",
    "REFRAME_SCHEMA",
    "REFRAME_VERSION",
    "ContentDims",
    "CropRect",
    "GamerZone",
    "Layout",
    "OutputGeometry",
    "PadBars",
    "ReframePlan",
    "SourceGeometry",
    "build_reframe_plan",
    "compute_blur_pad",
    "compute_crop",
    "compute_gamer_zones",
    "cover_crop",
    "plan_for_dims",
    "round_even",
    "strategy_for",
]
