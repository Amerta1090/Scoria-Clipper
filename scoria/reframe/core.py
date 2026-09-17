"""Reframe plan builder — pure: MediaInfo + config → ReframePlan (Sprint 8).

No I/O and no RNG: the plan is a closed-form function of the media dims and the
`reframe` config (center mode), so identical inputs always produce an identical
plan — `deterministic: true` by construction (ARCHITECTURE.md §7). `render/`
(Sprint 9) consumes the plan to build the ffmpeg filter graph; this module
never touches ffmpeg.
"""

from __future__ import annotations

from scoria.config.schema import ReframeConfig, ScoriaConfig
from scoria.ingest.models import MediaInfo
from scoria.reframe.geometry import compute_blur_pad, compute_crop, strategy_for
from scoria.reframe.models import (
    REFRAME_PLAN_VERSION,
    REFRAME_SCHEMA,
    REFRAME_VERSION,
    OutputGeometry,
    ReframePlan,
    SourceGeometry,
)


def plan_for_dims(source_w: int, source_h: int, reframe: ReframeConfig) -> ReframePlan:
    """Compute the 9:16 plan for a source of `source_w`×`source_h` (pure).

    Exposed separately from `build_reframe_plan` so the geometry is testable
    without constructing a `MediaInfo` (L0 unit tests).
    """
    source_ar = round(source_w / source_h, 4)
    out = reframe.output
    strategy = strategy_for(source_w, source_h, reframe.blurbad_threshold)
    crop = content = pad = None
    if strategy == "crop":
        crop = compute_crop(source_w, source_h)
    elif strategy == "blur_pad":
        content, pad = compute_blur_pad(source_w, source_h, out.width, out.height)
    return ReframePlan(
        reframe_version=REFRAME_PLAN_VERSION,
        mode=reframe.mode,
        strategy=strategy,
        source=SourceGeometry(width=source_w, height=source_h, aspect_ratio=source_ar),
        output=OutputGeometry(width=out.width, height=out.height),
        crop=crop,
        content=content,
        pad=pad,
    )


def build_reframe_plan(media: MediaInfo, cfg: ScoriaConfig) -> ReframePlan:
    """MediaInfo (analysis.json `media` section) + config → ReframePlan."""
    return plan_for_dims(media.width, media.height, cfg.reframe)


__all__ = [
    "REFRAME_PLAN_VERSION",
    "REFRAME_SCHEMA",
    "REFRAME_VERSION",
    "build_reframe_plan",
    "plan_for_dims",
]
