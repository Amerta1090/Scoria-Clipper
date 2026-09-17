"""Pure crop/blur-pad geometry: AR → even-dim, chroma-aligned plan (Sprint 8).

All functions are closed-form and deterministic — the center path needs no
smoothing or state, so identical inputs always produce identical outputs
(ARCHITECTURE.md §7). Rounding follows the `reframe.even_dim` contract: crop
dimensions and placement offsets are rounded to even integers so YUV 4:2:0
chroma stays aligned after the scale stage (CONFIGURATION.md §1 `reframe`).
"""

from __future__ import annotations

from typing import Literal

from scoria.reframe.models import ContentDims, CropRect, PadBars

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
