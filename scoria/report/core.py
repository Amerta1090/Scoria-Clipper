"""Report orchestration: existing JSON + source video -> `previews/` + report.html.

`preview_project` writes the still assets (per-clip thumbnail, contact sheet,
timeline strip) and `previews.json`; `report_project` adds the self-contained
`report.html`. Report/preview never re-analyze (ARCHITECTURE.md §9): clip timings
come from ranking.json, geometry from `analysis.media`, and the only extra runtime
input is the source video as the ffmpeg decode input.

Determinism: stills are grabbed through the pinned ffmpeg surface
(`util/ffmpeg.run_ffmpeg` — `-nostdin`, fixed args, `-ss` input seek like render),
the timeline is pure SVG, and `previews.json` is written under the 4-decimal
serialization contract (ADR-010).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scoria.config.schema import ScoriaConfig
from scoria.errors import PipelineError
from scoria.project import read_json, write_json
from scoria.report.graph import contact_sheet_args, sample_times, thumbnail_args, timeline_svg
from scoria.report.html import render_report_html
from scoria.report.models import ClipPreview, PreviewsInfo, TimelineAsset
from scoria.util import ffmpeg
from scoria.util.logging import get_logger

logger = get_logger("report")

TIMELINE_HEIGHT = 48
# Strip is 4 preview widths wide — deterministic, no new config key.
TIMELINE_WIDTH_FACTOR = 4


def _load(analysis_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any], Path]:
    """Read + validate analysis.json and its sibling ranking.json."""
    analysis_path = Path(analysis_path)
    project_dir = analysis_path.parent
    analysis = read_json(analysis_path)
    if not isinstance(analysis, dict) or analysis.get("schema") != "analysis":
        raise PipelineError(
            f"not an analysis document (schema != 'analysis'): {analysis_path}",
            hint="run `clipper analyze VID` first, then `clipper report PROJECT_DIR`",
        )
    media = analysis.get("media")
    if not isinstance(media, dict) or media.get("schema") != "media-info":
        raise PipelineError(
            f"analysis has no media section: {analysis_path}",
            hint="report needs width/height/duration/source from `clipper analyze`",
        )
    ranking_path = project_dir / "ranking.json"
    if not ranking_path.is_file():
        raise PipelineError(
            "report needs the sibling ranking.json",
            hint=f"expected {ranking_path}; run `clipper rank <candidates.json>` first",
        )
    ranking = read_json(ranking_path)
    if not isinstance(ranking, dict) or ranking.get("schema") != "ranking":
        raise PipelineError(f"not a ranking document (schema != 'ranking'): {ranking_path}")
    if not ranking.get("selected"):
        raise PipelineError(
            f"ranking has no selected clips: {ranking_path}",
            hint="run `clipper rank --top N` with a positive N so there is a clip to preview",
        )
    return project_dir, media, ranking, ranking_path


def _grab(source: str, t: float, out_path: Path, width: int) -> None:
    try:
        ffmpeg.run_ffmpeg(thumbnail_args(source, t, out_path, width))
    except PipelineError as exc:
        raise PipelineError(
            f"thumbnail grab failed at {t:.3f}s of {source!r}",
            hint=exc.hint,
        ) from exc


def _build_assets(
    project_dir: Path,
    media: dict[str, Any],
    ranking: dict[str, Any],
    ranking_path: Path,
    cfg: ScoriaConfig,
) -> PreviewsInfo:
    source = str(media.get("source") or "")
    if not Path(source).is_file():
        raise PipelineError(
            f"source video not found: {source}",
            hint="report decodes stills from the source video only (no re-analysis)",
        )
    media_duration = float(media.get("duration") or 0.0)
    if media_duration <= 0.0:
        raise PipelineError(
            f"analysis media has non-positive duration: {media_duration}",
            hint="re-run `clipper analyze` on a valid media file",
        )
    width = cfg.report.preview_width
    samples = cfg.report.per_candidate_strips
    previews_dir = project_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)

    clips: list[ClipPreview] = []
    for raw in ranking["selected"]:
        clip_id = str(raw["id"])
        start = float(raw["start"])
        end = float(raw["end"])
        duration = float(raw["duration"])
        mid = (start + end) / 2.0

        thumb_path = previews_dir / f"{clip_id}.png"
        _grab(source, mid, thumb_path, width)

        times = sample_times(start, end, samples)
        frames: list[Path] = []
        for index, t in enumerate(times):
            frame_path = previews_dir / f"{clip_id}.frame{index}.png"
            _grab(source, t, frame_path, width)
            frames.append(frame_path)
        sheet_path = previews_dir / f"{clip_id}.sheet.png"
        ffmpeg.run_ffmpeg(contact_sheet_args(frames, sheet_path))
        for frame_path in frames:
            frame_path.unlink(missing_ok=True)

        clips.append(
            ClipPreview(
                id=clip_id,
                rank=int(raw["rank"]),
                start=start,
                end=end,
                duration=duration,
                mid=mid,
                thumbnail=f"previews/{thumb_path.name}",
                contact_sheet=f"previews/{sheet_path.name}",
                strip_times=times,
            )
        )
        logger.info("preview %s -> %s (+ %d-frame sheet)", clip_id, thumb_path, len(frames))

    timeline_width = width * TIMELINE_WIDTH_FACTOR
    timeline_path = previews_dir / "timeline.svg"
    timeline_path.write_text(
        timeline_svg(media_duration, ranking["selected"], timeline_width, TIMELINE_HEIGHT),
        encoding="utf-8",
    )

    doc = PreviewsInfo(
        input=str(ranking_path),
        source=source,
        media_duration=media_duration,
        preview_width=width,
        samples_per_clip=samples,
        clips=clips,
        timeline=TimelineAsset(
            file="previews/timeline.svg",
            width=timeline_width,
            height=TIMELINE_HEIGHT,
            media_duration=media_duration,
        ),
    )
    write_json(previews_dir / "previews.json", doc)
    logger.info(
        "%d preview(s) -> %s",
        len(clips),
        previews_dir,
        extra={"stage": "report", "artifact": str(previews_dir / "previews.json")},
    )
    return doc


def preview_project(analysis_path: Path, *, cfg: ScoriaConfig) -> PreviewsInfo:
    """Write `previews/` still assets + `previews.json` (no report.html)."""
    project_dir, media, ranking, ranking_path = _load(analysis_path)
    return _build_assets(project_dir, media, ranking, ranking_path, cfg)


def report_project(analysis_path: Path, *, cfg: ScoriaConfig) -> Path:
    """Write `previews/` + `previews.json` and the self-contained `report.html`."""
    project_dir, media, ranking, ranking_path = _load(analysis_path)
    doc = _build_assets(project_dir, media, ranking, ranking_path, cfg)
    html_text = render_report_html(
        previews=doc.model_dump(mode="json", by_alias=True),
        ranking=ranking,
        cfg=cfg,
        project_dir=project_dir,
    )
    out_path = project_dir / "report.html"
    out_path.write_text(html_text, encoding="utf-8")
    logger.info(
        "report.html -> %s",
        out_path,
        extra={"stage": "report", "artifact": str(out_path)},
    )
    return out_path
