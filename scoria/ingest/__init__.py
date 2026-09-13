"""Ingestion: ffprobe metadata, container validation, stream detection (Sprint 1).

`analysis.json.media` is the single source of truth for stream identity, duration,
aspect ratio, timebase and the analysis window — all timestamps normalized to
seconds.
"""

from scoria.ingest.core import build_media
from scoria.ingest.ffprobe import probe, select_video_stream, stream_kinds
from scoria.ingest.io import resolve_input, spool_stream
from scoria.ingest.models import (
    ANALYSIS_SCHEMA,
    FILE_SOURCE,
    MEDIA_SCHEMA,
    STDIN_SOURCE,
    AnalysisWindow,
    MediaInfo,
)
from scoria.ingest.pipeline import analyze_video

__all__ = [
    "ANALYSIS_SCHEMA",
    "FILE_SOURCE",
    "MEDIA_SCHEMA",
    "STDIN_SOURCE",
    "AnalysisWindow",
    "MediaInfo",
    "analyze_video",
    "build_media",
    "probe",
    "resolve_input",
    "select_video_stream",
    "spool_stream",
    "stream_kinds",
]
