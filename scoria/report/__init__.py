"""Sprint 10 report stage: preview assets + report.html + explain renderers.

Public surface:
- `preview_project` / `report_project` — existing analysis.json + ranking.json +
  source video -> `previews/` stills + `previews.json` (+ `report.html`).
- `explain_one` / `render_explain` — embedded `ScoreBreakdown` + ranking decision
  for one clip id, as text / JSON / YAML.
"""

from scoria.report.core import preview_project, report_project
from scoria.report.explain import explain_one, render_explain
from scoria.report.html import render_report_html
from scoria.report.models import (
    PREVIEW_VERSION,
    PREVIEWS_SCHEMA,
    PREVIEWS_VERSION,
    ClipPreview,
    PreviewsInfo,
    TimelineAsset,
)

__all__ = [
    "PREVIEWS_SCHEMA",
    "PREVIEWS_VERSION",
    "PREVIEW_VERSION",
    "ClipPreview",
    "PreviewsInfo",
    "TimelineAsset",
    "explain_one",
    "preview_project",
    "render_explain",
    "render_report_html",
    "report_project",
]
