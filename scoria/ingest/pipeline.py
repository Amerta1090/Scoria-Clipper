"""The `clipper analyze` stage: input → probe/validate → analysis.json (+ manifest).

Orchestrates project-dir resolution, input resolution (stdin spooling) and the
media contract. It is deliberately thin — all ffprobe/validation logic lives in
`ingest.core`/`ingest.ffprobe` so later stages reuse it unchanged.
"""

from __future__ import annotations

from pathlib import Path

from scoria.config.schema import ScoriaConfig
from scoria.ingest.core import build_media
from scoria.ingest.io import resolve_input
from scoria.ingest.models import ANALYSIS_SCHEMA, MediaInfo
from scoria.project.dirs import prepare_project_dir, project_temp_dir, resolve_project_dir
from scoria.project.jsonio import write_json


def analyze_video(video_arg: str, config: ScoriaConfig) -> tuple[MediaInfo, Path]:
    """Probe/validate `video_arg` and write analysis.json; return (media, project_dir)."""
    project_dir = resolve_project_dir(config, video_arg)
    stdin_mode = video_arg == "-"
    if stdin_mode:
        prepare_project_dir(project_dir, overwrite=config.project.overwrite)
    input_path, source_kind = resolve_input(
        video_arg, tmp_dir=project_temp_dir(project_dir, config)
    )
    if not stdin_mode:
        prepare_project_dir(project_dir, overwrite=config.project.overwrite)
    media = build_media(input_path, config, source=video_arg, source_kind=source_kind)
    analysis_path = write_json(
        project_dir / "analysis.json", {"schema": ANALYSIS_SCHEMA, "media": media}
    )
    return media, analysis_path.parent
