"""Pure crop/blur-pad + two-zone gamer geometry: AR → even-dim, chroma-aligned plan.

The center path (Sprint 8) covers crop/scale/blur-pad; the gamer path (Sprint 12)
adds `cover_crop` (zone fill) and `compute_gamer_zones` (two-zone vertical stack).
All functions are closed-form and deterministic — no smoothing or state, so
identical inputs always produce identical outputs (ARCHITECTURE.md §7). Rounding
follows the `reframe.even_dim` contract: crop dimensions and placement offsets are
rounded to even integers so YUV 4:2:0 chroma stays aligned after the scale stage
(CONFIGURATION.md §1 `reframe`).
"""

from __future__ import annotations

from typing import Literal

from scoria.config.schema import GamerConfig
from scoria.reframe.models import ContentDims, CropRect, GamerZone, PadBars

TARGET_ASPECT = 9 / 16


def round_even(value: float) -> int:
    """Round to the nearest even integer (chroma alignment, banker's ties)."""
    return int(2 * round(value / 2))


def _ar(width: int, height: int) -> float:
    return width / height


def strategy_for(
    source_w: int, source_h: int, blurbad_threshold: float
) -> Literal["crop", "scale", "blur_pad"]:
    """Pick the reframe strategy from the source AR (closed-form, deterministic).

    - source already 9:16                          → `scale`
    - 9:16 < source AR ≤ `blurbad_threshold`       → `crop` (center window)
    - source AR > `blurbad_threshold` (very-wide)  → `blur_pad` (would deep-crop)
    - source AR < 9:16 (taller than 9:16)          → `blur_pad` (never deep-crops
      vertically — ARCHITECTURE.md §9)
    """
    ar = _ar(source_w, source_h)
    if abs(ar - TARGET_ASPECT) < 1e-9:
        return "scale"
    if ar < TARGET_ASPECT or ar > blurbad_threshold:
        return "blur_pad"
    return "crop"


def compute_crop(source_w: int, source_h: int) -> CropRect:
    """Center crop yielding exactly 9:16 at source resolution (even dims/offsets).

    Crop height = full source height; crop width = round_even(h × 9/16); x =
    centered then even-aligned. The even crop width + even offset can never
    overflow the source (offsets stay ≤ (w−c)/2+1 with c ≤ w), so no in-bounds
    clamp is needed after centering — only the width clamp for out-of-contract
    inputs narrower than 9:16.
    """
    crop_w = round_even(source_h * TARGET_ASPECT)
    if crop_w > source_w:
        crop_w = source_w - (source_w % 2)
    crop_x = round_even((source_w - crop_w) / 2)
    return CropRect(x=crop_x, y=0, width=crop_w, height=source_h)


def compute_blur_pad(
    source_w: int, source_h: int, target_w: int, target_h: int
) -> tuple[ContentDims, PadBars]:
    """Contain-scale the source inside the target and measure the blur bars.

    `content` is the largest even-dimens version of the source that fits the
    target while preserving AR; `pad` reports the even bar sizes (two of the
    four are 0). `render/` (Sprint 9) fills the bars with blurred source
    material; this function only computes where the bars go.
    """
    scale = min(target_w / source_w, target_h / source_h)
    content_w = min(round_even(source_w * scale), target_w - (target_w % 2))
    content_h = min(round_even(source_h * scale), target_h - (target_h % 2))
    pad_left = round_even((target_w - content_w) / 2)
    pad_right = target_w - content_w - pad_left
    pad_top = round_even((target_h - content_h) / 2)
    pad_bottom = target_h - content_h - pad_top
    return (
        ContentDims(width=content_w, height=content_h),
        PadBars(top=pad_top, bottom=pad_bottom, left=pad_left, right=pad_right),
    )


def cover_crop(source_w: int, source_h: int, target_w: int, target_h: int) -> CropRect:
    """Source-space window that fully covers `target_w`×`target_h` after a scale.

    The gamer zone fill (Sprint 12): unlike `compute_crop` (center mode keeps the
    *whole* height), cover-fit crops both axes so even a source wider or taller
    than the zone can tile it exactly — no bars, no overlap. The window maps to
    the target under a single `scale` factor; dims/offsets are even-rounded
    (chroma) and defensively clamped in-bounds.
    """
    scale = max(target_w / source_w, target_h / source_h)
    crop_w = round_even(target_w / scale)
    crop_h = round_even(target_h / scale)
    crop_x = round_even((source_w - crop_w) / 2)
    crop_y = round_even((source_h - crop_h) / 2)
    if crop_w > source_w:
        crop_w = source_w - (source_w % 2)
    if crop_h > source_h:
        crop_h = source_h - (source_h % 2)
    if crop_x + crop_w > source_w:
        crop_x = source_w - crop_w - ((source_w - crop_w) % 2)
    if crop_y + crop_h > source_h:
        crop_y = source_h - crop_h - ((source_h - crop_h) % 2)
    return CropRect(x=max(crop_x, 0), y=max(crop_y, 0), width=crop_w, height=crop_h)


def compute_gamer_zones(
    source_w: int, source_h: int, out_w: int, out_h: int, gamer: GamerConfig
) -> list[GamerZone]:
    """Two-zone vertical stack geometry for `mode: gamer` (Sprint 12).

    - gameplay zone (top): `round_even(out_h × v_fraction)` tall, full canvas
      width; fed by a center-anchored cover-fit crop of the whole source.
    - facecam zone (bottom): the canvas remainder (even by construction, so the
      two zones sum exactly to `out_h`); fed by the configured normalized source
      region, cover-fitted inside it and offset by the region's origin.

    Both zones are even-dim, in-bounds, non-overlapping and tile the canvas
    exactly — closed-form and deterministic (no RNG). `render/` composites them
    with `split` + `vstack`.
    """
    if source_w < 2 or source_h < 2:
        # Degenerate out-of-contract input: no valid even zone window. Callers
        # only see real media (ffprobe dims ≥ 2), so this is defensive totality.
        return [
            GamerZone(
                role="gameplay",
                crop=CropRect(x=0, y=0, width=0, height=0),
                x=0,
                y=0,
                width=out_w,
                height=out_h,
            )
        ]

    gameplay_h = round_even(out_h * gamer.gameplay.v_fraction)
    facecam_h = out_h - gameplay_h
    gameplay_crop = cover_crop(source_w, source_h, out_w, gameplay_h)

    region = gamer.facecam.region

    def _clamp_even(value: float, cap: int) -> int:
        even = min(max(round_even(value), 0), cap)
        return even - (even % 2)

    region_x = _clamp_even(source_w * region.x, max(source_w - 2, 0))
    region_y = _clamp_even(source_h * region.y, max(source_h - 2, 0))
    region_w = _clamp_even(source_w * region.w, source_w - region_x)
    region_h = _clamp_even(source_h * region.h, source_h - region_y)
    inner = cover_crop(region_w, region_h, out_w, facecam_h)
    facecam_crop = CropRect(
        x=region_x + inner.x,
        y=region_y + inner.y,
        width=inner.width,
        height=inner.height,
    )
    return [
        GamerZone(
            role="gameplay",
            crop=gameplay_crop,
            x=0,
            y=0,
            width=out_w,
            height=gameplay_h,
        ),
        GamerZone(
            role="facecam",
            crop=facecam_crop,
            x=0,
            y=gameplay_h,
            width=out_w,
            height=facecam_h,
        ),
    ]
