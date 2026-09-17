"""Render: ranking.json + analysis.json (+reframe/captions) → clips/ (Sprint 9).

`render_project` is the entry point: it turns the JSON artifacts into an ffmpeg
filter graph (crop/scale/blur-pad from reframe.json, optional libass burn-in of
the caption sidecars, static-gain loudness from analysis.json.audio) and encodes
each selected clip atomically under `clips/<clip_id>.mp4` (ADR-019). Everything
derives from the artifacts — never re-derived from the source at render time
(ARCHITECTURE.md §9 — render-without-reanalyze). The pure math lives in
`graph.py`; the orchestration in `core.py`.
"""

from scoria.render.core import render_project
from scoria.render.graph import audio_gain_db, build_video_chain, escape_filter_path, with_burn
from scoria.render.models import (
    RENDER_PLAN_VERSION,
    RENDER_SCHEMA,
    RENDER_VERSION,
    AudioSettings,
    ClipRenderResult,
    RenderDoc,
    VideoSettings,
)

__all__ = [
    "RENDER_PLAN_VERSION",
    "RENDER_SCHEMA",
    "RENDER_VERSION",
    "AudioSettings",
    "ClipRenderResult",
    "RenderDoc",
    "VideoSettings",
    "audio_gain_db",
    "build_video_chain",
    "escape_filter_path",
    "render_project",
    "with_burn",
]
