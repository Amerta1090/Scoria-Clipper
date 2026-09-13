"""Project dir + temp dir resolution (ARCHITECTURE.md §6, CONFIGURATION.md §1).

`project.dir: "auto"` means `<video>.scoria/` in the current working directory.
Stdin input (`-`) has no filename to derive from, so it needs an explicit
`--output` / `project.dir` — enforced here as a UsageError.
"""

from __future__ import annotations

from pathlib import Path

from scoria.config.schema import ScoriaConfig
from scoria.errors import PipelineError, UsageError

DEFAULT_TEMP_NAME = "tmp"


def resolve_project_dir(config: ScoriaConfig, video_arg: str) -> Path:
    if config.project.dir != "auto":
        return Path(config.project.dir)
    if video_arg == "-":
        raise UsageError(
            "stdin input needs an explicit project dir",
            hint="pass -o/--output DIR (the 'auto' default needs a filename)",
        )
    name = Path(video_arg).name.strip() or "input"
    return Path(f"{name}.scoria")


def project_temp_dir(project_dir: Path, config: ScoriaConfig) -> Path:
    if config.project.temp_dir != "auto":
        return Path(config.project.temp_dir)
    return Path(project_dir) / DEFAULT_TEMP_NAME


def prepare_project_dir(project_dir: Path, *, overwrite: bool) -> Path:
    """Refuse to reuse a non-empty project dir unless --overwrite; then mkdir."""
    project_dir = Path(project_dir)
    if project_dir.exists() and not overwrite:
        try:
            entries = list(project_dir.iterdir())
        except OSError:
            entries = []
        if entries:
            raise PipelineError(
                f"project dir {project_dir} already exists and is not empty",
                hint="pass --overwrite to replace its artifacts",
            )
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir
