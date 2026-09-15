"""Visual analysis pipeline entry points (Sprint 4 scene-detection scope).

Mirrors scoria/transcript/pipeline.py: an `analyze_<kind>` function that returns
`(result, degraded_flags)` and raises the module's error type on runtime failure
so linting and exit codes are uniform across analysis stages.
"""

from __future__ import annotations

from pathlib import Path

from scoria.config.schema import ScoriaConfig
from scoria.errors import MediaError, PipelineError
from scoria.ingest.models import MediaInfo
from scoria.util.logging import get_logger
from scoria.visual.models import VisualInfo
from scoria.visual.scene import detect_scenes

logger = get_logger("scoria.visual")


def analyze_visual(
    input_path: Path,
    config: ScoriaConfig,
    media: MediaInfo,
) -> tuple[VisualInfo | None, list[str]]:
    """Run scene detection over the analysis window. Returns (info, degraded).

    A `--no-visual` run returns (None, ["visual"]) and is not an error; the
    consumer treats the visual section as absent. A runtime failure is a
    MediaError (exit 1) reusing the extract / transcription convention.
    """
    if not config.visual.enabled:
        logger.info("visual scene detection disabled")
        return None, ["visual"]

    window = media.analysis
    frame = config.media.frame
    threshold = config.segment.scene_detection_threshold
    try:
        info = detect_scenes(
            input_path,
            start=window.start,
            end=window.end,
            fps=frame.fps,
            width=frame.width,
            height=frame.height,
            threshold=threshold,
        )
    except PipelineError as exc:
        raise MediaError(f"visual scene pass failed for {input_path.name}", hint=exc.hint) from exc
    return info, []
