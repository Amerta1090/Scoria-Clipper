"""Typed visual output: the `visual` section of analysis.json.

Minimal Sprint 4 contract (ARCHITECTURE.md §5.2): the scene-change list only.
Scene changes are detected with ffmpeg's `scdet` filter over the decimated
fps=4 gray 64×36 pass; each hit carries the media timestamp (absolute seconds)
and the normalized score in [0, 1] (scdet reports a percentage; we divide by
100 so the stored scale matches the config `segment.scene_detection_threshold`).
Motion intensity and the `visual_activity` sub-score land in a later sprint.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VISUAL_SCHEMA = "visual-info"


class SceneChange(BaseModel):
    time: float
    score: float


class VisualInfo(BaseModel):
    """`scenes` are sorted by time; `threshold` is the [0,1] config value used."""

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["visual-info"] = Field(VISUAL_SCHEMA, alias="schema")
    fps: int
    threshold: float
    scenes: list[SceneChange]
    scene_count: int
