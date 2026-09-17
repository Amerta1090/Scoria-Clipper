"""Render orchestration: ranking.json + analysis.json (+ reframe/captions) → clips/.

`render_project` is the single entry used by the CLI. Render never re-analyzes the
source (ARCHITECTURE.md §9): clip timings come from ranking.json, geometry from
reframe.json (built automatically from analysis.media when missing — closed-form,
no analysis rerun), captions from the id-keyed sidecars (or built via `captions/`),
loudness from analysis.json.audio, and the only runtime input besides the JSON
artifacts is the source video itself as the ffmpeg decode input.

Determinism: every ffmpeg call goes through the pinned surface
(`util/ffmpeg.run_ffmpeg` — `-nostdin`, fixed args), encodes with a fixed
thread count, and writes output atomically (temp file → rename).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from scoria.captions import build_captions, write_caption_sidecars
from scoria.config.schema import ScoriaConfig
from scoria.errors import PipelineError
from scoria.ingest import MediaInfo
from scoria.project import read_json, write_json, write_manifest
from scoria.reframe import build_reframe_plan
from scoria.reframe.models import ReframePlan
from scoria.render.graph import audio_gain_db, build_video_chain, filters_string, with_burn
from scoria.render.models import (
    AudioSettings,
    ClipRenderResult,
    RenderDoc,
    VideoSettings,
)
from scoria.util import ffmpeg
from scoria.util.logging import get_logger

logger = get_logger("render")


def _ranking_doc(ranking_path: Path) -> dict[str, Any]:
    ranking = read_json(ranking_path)
    if not isinstance(ranking, dict) or ranking.get("schema") != "ranking":
        raise PipelineError(
            f"not a ranking document (schema != 'ranking'): {ranking_path}",
            hint="run `clipper rank <candidates.json>` first, then `clipper render`",
        )
    selected = ranking.get("selected")
    if not isinstance(selected, list) or not selected:
        raise PipelineError(
            f"ranking has no selected clips: {ranking_path}",
            hint="run `clipper rank` with a positive --top so at least one clip is selected",
        )
    return ranking


def _media_info(analysis: dict[str, Any], analysis_path: Path) -> MediaInfo:
    media = analysis.get("media")
    if not isinstance(media, dict) or media.get("schema") != "media-info":
        raise PipelineError(
            f"analysis has no media section: {analysis_path}",
            hint="run `clipper analyze VID` first (render needs width/height/duration/source)",
        )
    return MediaInfo(**media)


def _reframe_plan(
    analysis: dict[str, Any], cfg: ScoriaConfig, project_dir: Path, *, rebuild: bool
) -> ReframePlan:
    """Load reframe.json, or build it from analysis.media (pure, no re-analysis)."""
    reframe_path = project_dir / "reframe.json"
    if reframe_path.is_file() and not rebuild:
        return ReframePlan(**read_json(reframe_path))
    plan = build_reframe_plan(_media_info(analysis, project_dir / "analysis.json"), cfg)
    write_json(reframe_path, plan)
    logger.info("reframe plan %s -> %s", plan.strategy, reframe_path)
    return plan


def _ensure_captions(
    ranking: dict[str, Any],
    analysis: dict[str, Any],
    cfg: ScoriaConfig,
    project_dir: Path,
    *,
    captions_on: bool,
) -> tuple[dict[str, Path], list[str]]:
    """Return {clip_id: .ass path} usable for burn + degradation flags.

    Uses existing sidecars when a complete set exists; otherwise rebuilds them
    via `captions/` (needs transcript words). Missing transcript or an
    `ass`-less `captions.format` degrades to no-burn (never silent — logged and
    stamped in the manifest).
    """
    if not captions_on:
        return {}, []
    cap_dir = project_dir / "captions"
    wanted = {str(clip["id"]) for clip in ranking["selected"]}
    present: dict[str, Path] = {}
    if cap_dir.is_dir():
        present = {p.stem: p for p in cap_dir.glob("*.ass") if p.stem in wanted}
    if len(present) == len(wanted):
        return present, []
    transcript = analysis.get("transcript")
    if not (isinstance(transcript, dict) and transcript.get("words")):
        logger.warning("captions requested but no word timestamps — rendering without burn")
        return {}, ["captions_unavailable"]
    if "ass" not in cfg.captions.format:
        logger.warning("captions.format excludes ass — cannot burn subtitles")
        return {}, ["burn_ass_format_missing"]
    doc = build_captions(ranking, analysis, cfg)
    files = write_caption_sidecars(doc, cap_dir, cfg)
    write_json(cap_dir / "captions.json", doc)
    logger.info("built %d caption sidecar(s) -> %s", len(files), cap_dir)
    return {p.stem: p for p in cap_dir.glob("*.ass") if p.stem in wanted}, []


def _clip_args(
    *,
    clip: dict[str, Any],
    source: str,
    plan: ReframePlan,
    cfg: ScoriaConfig,
    gain_db: float,
    ass_path: Path | None,
    out_path: Path,
    crf: int,
    preset: str,
    has_audio: bool,
    burn: bool,
) -> tuple[list[str], str, bool]:
    """Deterministic ffmpeg args for one clip (ends with `-y <out_path>`).

    `-ss`/`-t` come straight from ranking.json — the analysis frame-time seconds
    produced off the S1 ffprobe timebase (single source of truth, S9 risk note);
    input seeking (`-ss` before `-i`) is frame-accurate. Encoder surface is the
    pinned config: codec/CRF/preset/pix_fmt (+ `-movflags +faststart`), explicit
    `-threads`, video map either `0:v:0` (vf chain) or the filter_complex label.
    """
    fc, vf, label = build_video_chain(plan)
    burned = False
    if burn and ass_path is not None:
        fc, vf, label = with_burn(fc, vf, label, ass_path)
        burned = True
    args = [
        "-ss",
        f"{clip['start']:.4f}",
        "-t",
        f"{clip['duration']:.4f}",
        "-i",
        source,
        "-threads",
        str(cfg.render.threads),
        "-c:v",
        cfg.render.video.codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        cfg.render.video.pix_fmt,
    ]
    if cfg.render.video.faststart:
        args += ["-movflags", "+faststart"]
    # The atomic temp is `<name>.mp4.part`, whose suffix ffmpeg can't pin to a
    # muxer — pin the container explicitly so `.part` -> rename -> final `.mp4`
    # is byte-identical and the e2e surface stays deterministic (S9 DoD; same
    # keyed-clip surface asserted in L0/L5/L3).
    args += ["-f", "mp4"]
    if fc is not None:
        args += ["-filter_complex", fc, "-map", label]
    elif vf is not None:
        args += ["-vf", vf, "-map", "0:v:0"]
    if has_audio:
        args += ["-map", "0:a:0", "-c:a", cfg.render.audio.codec]
        if gain_db != 0.0:
            args += ["-af", f"volume={gain_db}dB"]
    else:
        args += ["-an"]
    args += ["-y", str(out_path)]
    return args, filters_string(fc, vf), burned


def _render_one(
    *,
    clip: dict[str, Any],
    source: str,
    plan: ReframePlan,
    cfg: ScoriaConfig,
    gain_db: float,
    ass_sidecars: dict[str, Path],
    clips_dir: Path,
    crf: int,
    preset: str,
    has_audio: bool,
    burn: bool,
    force: bool,
) -> ClipRenderResult:
    clip_id = str(clip["id"])
    final = clips_dir / f"{clip_id}.mp4"
    result = ClipRenderResult(
        id=clip_id,
        rank=int(clip["rank"]),
        start=float(clip["start"]),
        end=float(clip["end"]),
        duration=float(clip["duration"]),
        status="exists",
        output_file=str(final),
        gain_db=gain_db,
        burned=False,
    )
    if final.exists() and not force and not cfg.render.overwrite_output:
        logger.info("clip exists, skipping (render.overwrite_output=false): %s", final)
        return result
    part = final.with_name(final.name + ".part")
    args, filters, burned = _clip_args(
        clip=clip,
        source=source,
        plan=plan,
        cfg=cfg,
        gain_db=gain_db,
        ass_path=ass_sidecars.get(clip_id) if burn else None,
        out_path=part,
        crf=crf,
        preset=preset,
        has_audio=has_audio,
        burn=burn,
    )
    try:
        ffmpeg.run_ffmpeg(args)
    except PipelineError as exc:
        part.unlink(missing_ok=True)
        raise PipelineError(
            f"render of clip {clip_id} failed",
            hint=f"{exc.hint}\ncommand: ffmpeg {' '.join(arg for arg in args if arg)}",
        ) from exc
    os.replace(part, final)
    logger.info("rendered %s %.3fs..%.3fs -> %s", clip_id, result.start, result.end, final)
    result.status = "rendered"
    result.filters = filters
    result.burned = burned
    return result


def render_project(
    ranking_path: Path,
    *,
    cfg: ScoriaConfig,
    output_dir: Path,
    captions_on: bool = True,
    rebuild_reframe: bool = False,
    no_burn: bool = False,
    crf: int | None = None,
    preset: str | None = None,
    force: bool = False,
) -> RenderDoc:
    """Render every selected clip from JSON artifacts only.

    Returns the render.json document (also written alongside manifest.json to
    `output_dir`). `output_dir` defaults to the ranking's project dir in the
    CLI; clips land in `<output_dir>/clips/<clip_id>.mp4` (id-keyed, ADR-019).
    """
    ranking_path = Path(ranking_path)
    project_dir = ranking_path.parent
    ranking = _ranking_doc(ranking_path)
    analysis_path = project_dir / "analysis.json"
    if not analysis_path.is_file():
        raise PipelineError(
            "render needs the sibling analysis.json",
            hint=f"expected {analysis_path} next to {ranking_path}",
        )
    analysis = read_json(analysis_path)
    media = _media_info(analysis, analysis_path)
    source = media.source
    if not Path(source).is_file():
        raise PipelineError(
            f"source video not found: {source}",
            hint="render decodes from the source video only (no re-analysis); keep it reachable",
        )
    plan = _reframe_plan(analysis, cfg, project_dir, rebuild=rebuild_reframe)

    ass_sidecars, degraded = _ensure_captions(
        ranking, analysis, cfg, project_dir, captions_on=captions_on
    )
    libass = ffmpeg.has_filter("subtitles")
    burn = (not no_burn) and libass and bool(ass_sidecars)
    if (not no_burn) and ass_sidecars and not libass:
        degraded = [*degraded, "burn_sidecar_only"]
        logger.warning("subtitles (libass) filter unavailable — captions stay sidecar-only")

    audio = analysis.get("audio") or {}
    loudness = audio.get("loudness") or {}
    has_audio = bool(audio)
    integrated = loudness.get("integrated_lufs")
    true_peak = loudness.get("true_peak_db")
    gain_db = audio_gain_db(
        None if not isinstance(integrated, (int, float)) else float(integrated),
        target_lufs=cfg.render.audio.target_lufs,
        target_peak=cfg.render.audio.target_peak,
        measured_peak=None if not isinstance(true_peak, (int, float)) else float(true_peak),
    )

    over_crf = cfg.render.video.crf if crf is None else crf
    over_preset = cfg.render.video.preset if preset is None else preset

    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    results = [
        _render_one(
            clip=clip,
            source=source,
            plan=plan,
            cfg=cfg,
            gain_db=gain_db,
            ass_sidecars=ass_sidecars,
            clips_dir=clips_dir,
            crf=over_crf,
            preset=over_preset,
            has_audio=has_audio,
            burn=burn,
            force=force,
        )
        for clip in ranking["selected"]
    ]

    doc = RenderDoc(
        input=str(ranking_path),
        output=str(output_dir),
        threads=cfg.render.threads,
        video=VideoSettings(
            codec=cfg.render.video.codec,
            crf=over_crf,
            preset=over_preset,
            pix_fmt=cfg.render.video.pix_fmt,
            faststart=cfg.render.video.faststart,
        ),
        audio=AudioSettings(
            codec=cfg.render.audio.codec,
            method=cfg.render.audio.method,
            target_lufs=cfg.render.audio.target_lufs,
            target_peak=cfg.render.audio.target_peak,
            lra=cfg.render.audio.lra,
        ),
        burn=burn,
        degraded=degraded,
        clips=results,
    )
    write_json(output_dir / "render.json", doc)
    tools = {name: ffmpeg.version(name) for name in ("ffmpeg", "ffprobe")}
    write_manifest(
        output_dir,
        config=cfg,
        tools=tools,
        invocation=sys.argv,
        degraded=degraded,
    )
    rendered = sum(1 for result in results if result.status == "rendered")
    logger.info(
        "rendered %d/%d clip(s) -> %s (burn=%s, gain=%+.2f dB, degraded=%s)",
        rendered,
        len(results),
        clips_dir,
        burn,
        gain_db,
        degraded or "-",
        extra={"stage": "render", "artifact": str(output_dir / "render.json")},
    )
    return doc
