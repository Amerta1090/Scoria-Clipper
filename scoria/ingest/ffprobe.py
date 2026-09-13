"""ffprobe wrapper (JSON surface) and video-stream selection.

Every probe uses the pinned `run_ffprobe` from util/ so arguments never drift.
Failures are mapped to MediaError with ffprobe's stderr tail as the actionable hint
(`bad file errors are actionable` — SPRINT_PLANNING.md §Sprint 1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scoria.errors import MediaError, PipelineError
from scoria.util.ffmpeg import run_ffprobe


def probe(path: str | Path) -> dict[str, Any]:
    """Return the raw parsed ffprobe JSON (`format` + `streams`) for a media file."""
    try:
        proc = run_ffprobe([str(path)])
    except PipelineError as exc:
        raise MediaError(
            f"cannot probe media '{path}'", hint=exc.hint or "(no detail from ffprobe)"
        ) from exc
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(
            f"ffprobe returned unparsable JSON for '{path}'",
            hint=(proc.stderr or "").strip()[-800:] or "(no detail from ffprobe)",
        ) from exc
    return data


def stream_kinds(streams: list[dict[str, Any]]) -> str:
    kinds = sorted({str(stream.get("codec_type") or "?") for stream in streams})
    return ", ".join(kinds) if kinds else "(none)"


def select_video_stream(
    streams: list[dict[str, Any]], selection: str | int
) -> tuple[int, dict[str, Any]]:
    """Return (index, stream) for the configured video stream; error with detail."""
    total = len(streams)
    if selection == "auto":
        video = [(i, s) for i, s in enumerate(streams) if s.get("codec_type") == "video"]
        if not video:
            raise MediaError(
                "no video stream found in input",
                hint=f"stream kinds present: {stream_kinds(streams)}",
            )
        return video[0]
    if not isinstance(selection, int):
        raise MediaError(
            f"input.video_stream must be 'auto' or an integer index, got {selection!r}"
        )
    if selection < 0 or selection >= total:
        raise MediaError(
            f"input.video_stream index {selection} is out of range (0..{total - 1})",
            hint=f"stream kinds present: {stream_kinds(streams)}",
        )
    stream = streams[selection]
    if stream.get("codec_type") != "video":
        raise MediaError(
            f"stream {selection} is {stream.get('codec_type') or 'unknown'}, not video",
            hint=f"set input.video_stream to a video index; stream kinds present: "
            f"{stream_kinds(streams)}",
        )
    return selection, stream
