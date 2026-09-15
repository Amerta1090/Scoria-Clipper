"""ffmpeg `scdet` scene detection over the decimated content-analysis pass.

Detection approach (decided in Sprint 4, docs/DECISIONS.md ADR-015):

- run ffmpeg with a filter chain `trim=start..end,fps=4,scale=64:36,format=gray,
  scdet=threshold=<percent>` and a null muxer;
- scdet logs one INFO line per detected change on stderr of the form
  `[Parsed_scdet_3 @ 0x...] lavfi.scd.score: 99.609, lavfi.scd.time: 2`;
- `scdet.score` is a percentage (0-100), so the config threshold in [0,1]
  (`segment.scene_detection_threshold`, default 0.35) is multiplied by 100;
- `scdet.time` is the frame pts in seconds; `trim` keeps absolute media
  timestamps (an input-side `-ss` would reset them to near zero).

The `parse_scd_stderr` function is pure so it can be unit-tested without ffmpeg.
"""

from __future__ import annotations

import re
from pathlib import Path

from scoria.util.ffmpeg import run_ffmpeg
from scoria.util.logging import get_logger
from scoria.visual.models import SceneChange, VisualInfo

logger = get_logger("scoria.visual")

_SCD_RE = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+)\s*,\s*lavfi\.scd\.time:\s*([0-9.]+)")


def scdet_threshold_percent(config_threshold: float) -> int:
    """Map the [0,1] config threshold to scdet's percentage scale."""
    return int(round(config_threshold * 100.0))


def parse_scd_stderr(stderr: str) -> list[tuple[float, float]]:
    """Extract (absolute_seconds, normalized_score[0,1]) pairs from scdet stderr.

    Pure: no I/O. Lines are deduplicated and sorted by time so the result is
    deterministic regardless of libav's emit order.
    """
    hits: list[tuple[float, float]] = []
    seen: set[float] = set()
    for match in _SCD_RE.finditer(stderr):
        time = float(match.group(2))
        score = float(match.group(1)) / 100.0
        if time in seen:
            continue
        seen.add(time)
        hits.append((time, score))
    hits.sort(key=lambda ts: ts[0])
    return hits


def build_scdet_args(
    input_path: Path,
    *,
    start: float,
    end: float,
    fps: int,
    width: int,
    height: int,
    threshold_percent: int,
) -> list[str]:
    """Assemble the ffmpeg argv for one decimated scene-detection pass."""
    chain = f"fps={fps},scale={width}:{height},format=gray,scdet=threshold={threshold_percent}"
    if end is None:
        chain = f"trim=start={start:g},{chain}"
    else:
        chain = f"trim=start={start:g}:end={end:g},{chain}"
    return ["-v", "info", "-i", str(input_path), "-vf", chain, "-f", "null", "-"]


def detect_scenes(
    input_path: Path,
    *,
    start: float,
    end: float,
    fps: int,
    width: int,
    height: int,
    threshold: float,
) -> VisualInfo:
    """Run one scdet pass over [start, end) and return the detected changes.

    Scene times are clamped into [start, end] for robustness against libav
    timestamp edge cases at the boundaries.
    """
    percent = scdet_threshold_percent(threshold)
    args = build_scdet_args(
        input_path,
        start=start,
        end=end,
        fps=fps,
        width=width,
        height=height,
        threshold_percent=percent,
    )
    proc = run_ffmpeg(args)
    hits = parse_scd_stderr(proc.stderr or "")

    scenes = [
        SceneChange(time=max(start, min(end, time)), score=min(1.0, max(0.0, score)))
        for time, score in hits
    ]
    logger.info("scene detection: %d changes above threshold %.2f", len(scenes), threshold)
    return VisualInfo(
        schema="visual-info",
        fps=fps,
        threshold=threshold,
        scenes=scenes,
        scene_count=len(scenes),
    )
