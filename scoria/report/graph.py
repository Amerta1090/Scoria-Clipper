"""Pure builders for the report stage: deterministic ffmpeg args + timeline SVG.

Mirrors `render/graph.py`: every function here is a pure list/string builder with
zero I/O, so the exact asset surface can be pinned at L0. All ffmpeg calls go
through `util/ffmpeg.run_ffmpeg` (`-nostdin` pinned) — see `report/core.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# Fixed palette — byte-stable SVG, no theme lookup.
_BG = "#11151c"
_BLOCK_ODD = "#4f9cf9"
_BLOCK_EVEN = "#f59e0b"
_LABEL = "#e6edf3"

# Even-dim scale expression: same source AR -> same height, so a row of frames is
# hstack-compatible (no chroma-alignment surprises on odd sources).
_SCALE_EXPR = "scale={width}:-2"


def sample_times(start: float, end: float, count: int) -> list[float]:
    """`count` evenly spaced absolute still times across `[start, end]` (inclusive).

    `count == 1` samples the clip midpoint; `count >= 2` includes both edges. Pure
    geometry — the single source of truth for thumbnail *and* contact-sheet
    sampling, so tests can assert it without running ffmpeg.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    if count == 1:
        return [(start + end) / 2.0]
    step = (end - start) / (count - 1)
    return [start + i * step for i in range(count)]


def thumbnail_args(source: str, t: float, out_path: Path, width: int) -> list[str]:
    """Deterministic single-frame grab: `-ss t` input seek + one frame, even scale.

    `-ss` before `-i` matches the render clip surface (`render/core.py`), so stills
    land on the same frame-time seconds as rendering; `-frames:v 1` pins exactly
    one output image and `scale=w:-2` keeps the height even (chroma-aligned).
    """
    return [
        "-ss",
        f"{t:.4f}",
        "-i",
        source,
        "-frames:v",
        "1",
        "-vf",
        _SCALE_EXPR.format(width=width),
        "-y",
        str(out_path),
    ]


def contact_sheet_args(frame_paths: Sequence[Path], out_path: Path) -> list[str]:
    """One-row montage of same-AR stills via ffmpeg `hstack` (no ImageMagick).

    Frames were all scaled to the same width from the same source AR, so their
    heights match and `hstack` is well-defined. `inputs=N` is written explicitly
    for a deterministic graph; a single frame is passed straight through.
    """
    if not frame_paths:
        raise ValueError("contact sheet needs at least one frame")
    args: list[str] = []
    for frame in frame_paths:
        args += ["-i", str(frame)]
    if len(frame_paths) == 1:
        return [*args, "-frames:v", "1", "-y", str(out_path)]
    labels = "".join(f"[{i}:v]" for i in range(len(frame_paths)))
    args += [
        "-filter_complex",
        f"{labels}hstack=inputs={len(frame_paths)}",
        "-y",
        str(out_path),
    ]
    return args


def timeline_svg(
    media_duration: float,
    clips: Sequence[dict],
    width_px: int,
    height_px: int = 48,
) -> str:
    """Deterministic SVG strip: one proportional block per selected clip.

    `x` / `w` are `start/media_duration` and `duration/media_duration` of the strip
    width; block width has a 2 px floor so very short clips stay visible. Pure
    string output (no ffmpeg): byte-stable for the same inputs, embedded inline in
    report.html and written as `previews/timeline.svg`.
    """
    if media_duration <= 0:
        raise ValueError("media_duration must be > 0")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" '
        f'height="{height_px}" viewBox="0 0 {width_px} {height_px}">',
        f'<rect width="{width_px}" height="{height_px}" fill="{_BG}"/>',
    ]
    for clip in clips:
        x = round(float(clip["start"]) / media_duration * width_px, 2)
        w = max(2.0, round(float(clip["duration"]) / media_duration * width_px, 2))
        color = _BLOCK_ODD if int(clip["rank"]) % 2 else _BLOCK_EVEN
        parts.append(
            f'<rect x="{x}" y="6" width="{w}" height="{height_px - 12}" fill="{color}" rx="2"/>'
        )
        parts.append(
            f'<text x="{round(x + 3, 2)}" y="{height_px // 2 + 4}" fill="{_LABEL}" '
            f'font-size="11" font-family="monospace">#{int(clip["rank"])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
