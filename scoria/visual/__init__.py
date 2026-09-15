"""Minimal visual analysis: ffmpeg scdet scene changes (Sprint 4 scope)."""

from scoria.visual.models import VISUAL_SCHEMA, SceneChange, VisualInfo
from scoria.visual.pipeline import analyze_visual
from scoria.visual.scene import detect_scenes, parse_scd_stderr

__all__ = [
    "VISUAL_SCHEMA",
    "SceneChange",
    "VisualInfo",
    "analyze_visual",
    "detect_scenes",
    "parse_scd_stderr",
]
