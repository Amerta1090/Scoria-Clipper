"""MediaInfo builder: probe → stream selection → duration/AR/analysis-window validation.

Single source of truth for timestamps: everything downstream consumes seconds
normalized here (ARCHITECTURE.md §3, §5; SPRINT_PLANNING.md §Sprint 1 risk).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scoria.config.schema import ScoriaConfig
from scoria.errors import MediaError
from scoria.ingest.ffprobe import probe, select_video_stream
from scoria.ingest.models import AnalysisWindow, MediaInfo
from scoria.util.logging import get_logger

logger = get_logger("ingest")


def _seconds(value: Any) -> float | None:
    if value is None or value == "" or value == "N/A":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _seconds(value)
    if parsed is None:
        return None
    if not parsed.is_integer():
        return None
    return int(parsed)


def _resolve_duration(fmt: dict[str, Any], stream: dict[str, Any], source: str) -> float:
    for candidate in (fmt.get("duration"), stream.get("duration")):
        duration = _seconds(candidate)
        if duration is not None and duration > 0.0:
            return duration
    raise MediaError(
        f"cannot determine duration of '{source}'",
        hint="ffprobe reported neither a format nor a stream duration",
    )


def _dimensions(stream: dict[str, Any], source: str) -> tuple[int, int]:
    width = _int_or_none(stream.get("width"))
    height = _int_or_none(stream.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        raise MediaError(
            f"cannot determine video dimensions of '{source}'",
            hint=f"ffprobe reported width={stream.get('width')!r} height={stream.get('height')!r}",
        )
    return width, height


def _rotation(stream: dict[str, Any]) -> float:
    for side in stream.get("side_data_list", []):
        if side.get("side_data_type") == "Display Matrix":
            value = _seconds(side.get("rotation"))
            if value is not None:
                return value
    tags = stream.get("tags") or {}
    return _seconds(tags.get("rotate")) or 0.0


def _validate_duration(duration: float, config: ScoriaConfig, source: str) -> None:
    if duration < config.media.min_duration:
        raise MediaError(
            f"'{source}' duration {duration:.2f}s is below media.min_duration "
            f"({config.media.min_duration:g}s)",
            hint="cut a longer segment, or lower media.min_duration in the config",
        )
    if duration > config.media.max_duration:
        logger.warning(
            "'%s' duration %.2fs exceeds media.max_duration (%.0fs); analysis stays on "
            "the configured window",
            source,
            duration,
            config.media.max_duration,
            extra={"stage": "ingest"},
        )


def _analysis_window(config: ScoriaConfig, duration: float, source: str) -> AnalysisWindow:
    start = config.audio.analyze_start
    end = config.audio.analyze_end if config.audio.analyze_end > 0.0 else duration
    if start >= duration:
        raise MediaError(
            f"audio.analyze_start ({start:g}s) is not within '{source}' duration {duration:g}s",
            hint="lower audio.analyze_start",
        )
    if end > duration:
        raise MediaError(
            f"audio.analyze_end ({end:g}s) exceeds '{source}' duration {duration:g}s",
            hint="set audio.analyze_end ≤ media duration, or 0 to analyze the whole file",
        )
    return AnalysisWindow(start=start, end=end)


def build_media(
    path: Path,
    config: ScoriaConfig,
    *,
    source: str,
    source_kind: str,
) -> MediaInfo:
    """Probe `path` and validate it against config; return the `media` contract."""
    data = probe(path)
    streams = data.get("streams", [])
    if not streams:
        raise MediaError(
            f"no streams detected in '{source}'",
            hint="ffprobe reported an empty stream list",
        )
    index, stream = select_video_stream(streams, config.input.video_stream)
    fmt = data.get("format") or {}
    duration = _resolve_duration(fmt, stream, source)
    rotation = _rotation(stream)
    width, height = _dimensions(stream, source)
    display_w, display_h = (height, width) if abs(rotation) % 180 == 90 else (width, height)
    _validate_duration(duration, config, source)
    return MediaInfo(
        schema="media-info",
        source=source,
        source_kind=source_kind,
        container=fmt.get("format_name") or "unknown",
        stream_index=index,
        codec=stream.get("codec_name"),
        width=width,
        height=height,
        pixel_format=stream.get("pix_fmt"),
        duration=duration,
        start_time=_seconds(stream.get("start_time")) or 0.0,
        time_base=stream.get("time_base"),
        avg_frame_rate=stream.get("avg_frame_rate"),
        frame_count=_int_or_none(stream.get("nb_frames")),
        aspect_ratio=display_w / display_h,
        display_aspect_ratio=stream.get("display_aspect_ratio"),
        rotation=rotation,
        analysis=_analysis_window(config, duration, source),
    )
