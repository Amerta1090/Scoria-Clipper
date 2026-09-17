"""CLI entry point: `clipper` console script.

One-shot `clipper <video> [OPTIONS]` is handled by the entry wrapper in `main()`,
which rewrites it into the `run` subcommand (CLI_SPEC.md §1); `run` shares the flag
set with the top-level invocation. `analyze` (Sprint 1) is functional — it probes
and validates the input and writes analysis.json + manifest.json. The remaining
pipeline stage commands are registered stubs whose help matches CLI_SPEC.md;
running them raises PipelineError (exit 1). `config` (Sprint 0) and `verify-env`
are functional.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from scoria import envcheck
from scoria.captions import CAPTION_VERSION, CAPTIONS_VERSION, build_captions, write_ass, write_srt
from scoria.config import build_config, default_config, dump_yaml
from scoria.errors import PipelineError, ScoriaError
from scoria.ingest import MediaInfo, analyze_video
from scoria.project import normalize, read_json, write_json, write_manifest
from scoria.rank import RANK_VERSION, rank_candidates
from scoria.reframe import REFRAME_PLAN_VERSION, build_reframe_plan
from scoria.score import score_candidates
from scoria.score.models import SCORED_CANDIDATES_VERSION
from scoria.segment import CANDIDATES_VERSION, build_candidates
from scoria.transcript import whisper_cli_info, whisper_model_info
from scoria.util import ffmpeg
from scoria.util.logging import get_logger, setup_logging

err_console = Console(stderr=True, highlight=False)
logger = get_logger("analyze")


def _handle_error(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ScoriaError as exc:
            err_console.print(f"[red]error:[/red] {exc.message}")
            if exc.hint:
                err_console.print(f"[yellow]hint:[/yellow] {exc.hint}")
            raise typer.Exit(code=exc.exit_code) from exc

    return wrapper


def _cmd(fn):
    return _handle_error(fn)


app = typer.Typer(
    name="clipper",
    help="scoria — deterministic, local-first video clipping engine.",
    no_args_is_help=True,
    add_completion=False,
)

config_group = typer.Typer(help="Inspect and validate configuration.")
app.add_typer(config_group, name="config")


def _not_implemented(stage: str) -> None:
    raise PipelineError(
        f"`clipper {stage}` is not implemented yet (Sprints 1–11); "
        "this is the Sprint 0 foundation skeleton"
    )


def encode_summary(media: MediaInfo, analysis_path: Path) -> dict:
    """`--json` stage summary under the serialization contract (rounded floats)."""
    analysis = read_json(analysis_path)
    return {
        "media": normalize(media),
        "audio": normalize(analysis.get("audio")),
        "transcript": normalize(analysis.get("transcript")),
        "visual": normalize(analysis.get("visual")),
        "analysis": str(analysis_path),
    }


def _cli_overrides(
    output: Path | None,
    no_transcript: bool,
    no_captions: bool,
    vertical: bool,
    reframe_mode: str | None,
    keep_temp: bool,
    overwrite: bool,
) -> dict:
    overrides: dict = {"project": {"keep_temp": keep_temp, "overwrite": overwrite}}
    if output is not None:
        overrides["project"]["dir"] = str(output)
    if no_transcript:
        overrides["transcript"] = {"enabled": False}
    if reframe_mode is not None:
        overrides["reframe"] = {"mode": reframe_mode}
    return overrides


def _run_pipeline(
    config_path: Path | None,
    profile: str | None,
    output: Path | None,
    no_transcript: bool,
    no_captions: bool,
    vertical: bool,
    reframe_mode: str | None,
    keep_temp: bool,
    overwrite: bool,
) -> None:
    overrides = _cli_overrides(
        output, no_transcript, no_captions, vertical, reframe_mode, keep_temp, overwrite
    )
    build_config(path=config_path, profile=profile, overrides=overrides)
    _not_implemented("run")


# ---------------------------------------------------------------------------
# one-shot pipeline
# ---------------------------------------------------------------------------


@app.command(help="One-shot: analyze → segment → score → rank → captions → render → report.")
def run(
    video: Path = typer.Argument(..., help="Input video (or '-' for stdin)"),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Project dir (default <video>.scoria/)"
    ),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    top: int = typer.Option(3, "-t", "--top", help="Number of clips to render (default 3)"),
    no_transcript: bool = typer.Option(False, "--no-transcript", help="Skip STT"),
    no_visual: bool = typer.Option(False, "--no-visual", help="Skip frame pass"),
    no_captions: bool = typer.Option(False, "--no-captions", help="Skip caption burn-in"),
    vertical: bool = typer.Option(True, "--vertical/--no-vertical", help="Force 9:16 output"),
    reframe_mode: str | None = typer.Option(None, "--reframe", help="Reframe mode (MVP: center)"),
    keep_temp: bool = typer.Option(False, "--keep-temp", help="Keep analysis temporaries"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing project dir"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    _handle_error(
        lambda: _run_pipeline(
            config_path,
            profile,
            output,
            no_transcript,
            no_captions,
            vertical,
            reframe_mode,
            keep_temp,
            overwrite,
        )
    )()
    if json_output:
        typer.echo(json.dumps({"ok": True}, sort_keys=True))


# ---------------------------------------------------------------------------
# pipeline stage stubs (their sprint owns the real flags)
# ---------------------------------------------------------------------------


@app.command(help="Produce analysis.json — ffprobe metadata + validation (Sprint 1).")
@_cmd
def analyze(
    video: Path = typer.Argument(..., help="Input video (or '-' for stdin)"),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Project dir (default <video>.scoria/)"
    ),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    no_transcript: bool = typer.Option(False, "--no-transcript", help="Skip STT"),
    no_visual: bool = typer.Option(False, "--no-visual", help="Skip frame pass"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing project dir"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    overrides: dict = {}
    if output is not None:
        overrides["project"] = {"dir": str(output)}
    if overwrite:
        overrides.setdefault("project", {})["overwrite"] = True
    if no_transcript:
        overrides["transcript"] = {"enabled": False}
    if no_visual:
        overrides["visual"] = {"enabled": False}
    cfg = build_config(path=config_path, profile=profile, overrides=overrides)
    media, project_dir, degraded = analyze_video(str(video), cfg)
    tools = {name: ffmpeg.version(name) for name in ("ffmpeg", "ffprobe")}
    if cfg.transcript.enabled:
        tools["whisper-cli"] = whisper_cli_info(cfg.transcript)
        tools["whisper-model"] = whisper_model_info(cfg.transcript)
    write_manifest(
        project_dir,
        config=cfg,
        tools=tools,
        invocation=sys.argv,
        degraded=degraded,
    )
    analysis_path = project_dir / "analysis.json"
    logger.info(
        "media probed: %dx%d %s (%.2fs) -> %s",
        media.width,
        media.height,
        media.aspect_ratio,
        media.duration,
        analysis_path,
        extra={"stage": "analyze", "artifact": str(analysis_path)},
    )
    if json_output:
        summary = json.dumps(
            encode_summary(media, analysis_path), sort_keys=True, ensure_ascii=False
        )
        typer.echo(summary)


def _analysis_json_path(path: Path) -> Path:
    """Accept a project dir (containing analysis.json) or any JSON analysis doc."""
    if path.is_dir():
        return path / "analysis.json"
    if not path.is_file():
        raise PipelineError(
            f"analysis input not found: {path}",
            hint="run `clipper analyze VID` first, then `clipper segment ANALYSIS_DIR_OR_JSON`",
        )
    return path


@app.command(help="Produce raw candidates.json from analysis (Sprint 4).")
@_cmd
def segment(
    path: Path = typer.Argument(..., help="analysis.json or a scoria project dir"),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    cfg = build_config(path=config_path, profile=profile)
    analysis_path = _analysis_json_path(path)
    analysis = read_json(analysis_path)
    if not isinstance(analysis, dict) or analysis.get("schema") != "analysis":
        raise PipelineError(
            f"not an analysis document (schema != 'analysis'): {analysis_path}",
            hint="run `clipper analyze VID` first, then `clipper segment <analysis.json>`",
        )
    candidates = build_candidates(analysis, cfg)
    out_path = write_json(analysis_path.parent / "candidates.json", candidates)
    logger.info(
        "%d boundaries -> %d candidates -> %s",
        len(candidates["boundaries"]),
        len(candidates["candidates"]),
        out_path,
        extra={"stage": "segment", "artifact": str(out_path)},
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "candidates": len(candidates["candidates"]),
                    "boundaries": len(candidates["boundaries"]),
                    "input": str(analysis_path),
                    "output": str(out_path),
                },
                sort_keys=True,
            )
        )


@app.command(help="Enrich candidates.json with per-candidate ScoreBreakdowns (Sprint 5).")
@_cmd
def score(
    path: Path = typer.Argument(..., help="candidates.json or a scoria project dir"),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    cfg = build_config(path=config_path, profile=profile)
    candidates_path = _candidates_json_path(path)
    candidates = read_json(candidates_path)
    if not isinstance(candidates, dict) or candidates.get("schema") != "candidates":
        raise PipelineError(
            f"not a candidates document (schema != 'candidates'): {candidates_path}",
            hint="run `clipper segment <analysis.json>` first",
        )

    has_breakdowns = any("score" in c for c in candidates.get("candidates", []))
    analysis = None
    if candidates.get("version") == CANDIDATES_VERSION and not has_breakdowns:
        analysis_path = candidates_path.parent / "analysis.json"
        if not analysis_path.is_file():
            raise PipelineError(
                "a raw candidates document needs the sibling analysis.json on the first pass",
                hint=f"expected {analysis_path} next to {candidates_path}",
            )
        analysis = read_json(analysis_path)

    candidates = score_candidates(candidates, cfg, analysis_data=analysis)
    out_path = write_json(candidates_path, candidates)
    logger.info(
        "%d candidates scored (v%s) -> %s",
        len(candidates["candidates"]),
        candidates["scoring_version"],
        out_path,
        extra={"stage": "score", "artifact": str(out_path)},
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "candidates": len(candidates["candidates"]),
                    "scoring_version": candidates["scoring_version"],
                    "candidates_version": SCORED_CANDIDATES_VERSION,
                    "input": str(candidates_path),
                    "output": str(out_path),
                },
                sort_keys=True,
            )
        )


def _candidates_json_path(path: Path) -> Path:
    """Accept a project dir (containing candidates.json) or a candidates JSON doc."""
    if path.is_dir():
        return path / "candidates.json"
    if not path.is_file():
        raise PipelineError(
            f"candidates input not found: {path}",
            hint="run `clipper segment` first, then `clipper score CANDIDATES_DIR_OR_JSON`",
        )
    return path


@app.command(help="Rank scored candidates.json → diverse top-N (Sprint 6).")
@_cmd
def rank(
    path: Path = typer.Argument(..., help="candidates.json or a scoria project dir"),
    top: int = typer.Option(3, "-t", "--top", min=0, help="Max clips to select"),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    cfg = build_config(path=config_path, profile=profile)
    candidates_path = _candidates_json_path(path)
    candidates = read_json(candidates_path)
    if not isinstance(candidates, dict) or candidates.get("schema") != "candidates":
        raise PipelineError(
            f"not a candidates document (schema != 'candidates'): {candidates_path}",
            hint="run `clipper segment <analysis.json>` first",
        )
    scored = any(isinstance(c.get("score"), dict) for c in candidates.get("candidates", []))
    if not scored:
        raise PipelineError(
            "rank needs scored candidates (no embedded ScoreBreakdown found)",
            hint="run `clipper score <candidates.json>` first, then `clipper rank`",
        )
    ranking = rank_candidates(candidates, cfg, top=top)
    out_path = write_json(candidates_path.parent / "ranking.json", ranking)
    logger.info(
        "ranked %d candidates -> %d selected%s -> %s",
        len(candidates["candidates"]),
        len(ranking["selected"]),
        f" ({ranking['stop_reason']})" if ranking["stopped"] else "",
        out_path,
        extra={"stage": "rank", "artifact": str(out_path)},
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "candidates": len(candidates["candidates"]),
                    "selected": len(ranking["selected"]),
                    "rejected": len(ranking["rejected"]),
                    "stopped": ranking["stopped"],
                    "stop_reason": ranking["stop_reason"],
                    "rank_version": RANK_VERSION,
                    "input": str(candidates_path),
                    "output": str(out_path),
                },
                sort_keys=True,
            )
        )


@app.command(help="Render ranking.json → clips/ + captions/ (Sprint 9).")
@_cmd
def render(path: Path) -> None:
    _not_implemented("render")


@app.command(help="Write SRT + ASS sidecars from ranking.json (Sprint 7).")
@_cmd
def captions(
    path: Path = typer.Argument(..., help="ranking.json or a scoria project dir"),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    cfg = build_config(path=config_path, profile=profile)
    ranking_path = _ranking_json_path(path)
    ranking = read_json(ranking_path)
    if not isinstance(ranking, dict) or ranking.get("schema") != "ranking":
        raise PipelineError(
            f"not a ranking document (schema != 'ranking'): {ranking_path}",
            hint="run `clipper rank <candidates.json>` first",
        )
    analysis_path = ranking_path.parent / "analysis.json"
    if not analysis_path.is_file():
        raise PipelineError(
            "captions need the sibling analysis.json (transcript words)",
            hint=f"expected {analysis_path} next to {ranking_path}",
        )
    analysis = read_json(analysis_path)
    transcript = analysis.get("transcript")
    if not isinstance(transcript, dict) or transcript.get("schema") != "transcript-info":
        raise PipelineError(
            f"analysis has no transcript section: {analysis_path}",
            hint="run `clipper analyze` with transcript enabled (whisper), then re-score/re-rank",
        )
    if not transcript.get("words"):
        raise PipelineError(
            "transcript has no word timestamps, cannot build captions",
            hint="word timestamps need whisper -nfa --dtw (see DEPENDENCIES.md / ADR-013)",
        )
    doc = build_captions(ranking, analysis, cfg)
    out_dir = ranking_path.parent / "captions"
    write_json(out_dir / "captions.json", doc)
    files: list[str] = []
    for clip in doc.clips:
        if not clip.captions:
            continue
        if "srt" in cfg.captions.format:
            srt_path = out_dir / f"{clip.id}.srt"
            srt_path.write_text(write_srt(clip.captions), encoding="utf-8")
            files.append(str(srt_path))
        if "ass" in cfg.captions.format:
            ass_path = out_dir / f"{clip.id}.ass"
            ass_path.write_text(write_ass(clip.captions, cfg.captions.ass_style), encoding="utf-8")
            files.append(str(ass_path))
    total_captions = sum(len(clip.captions) for clip in doc.clips)
    logger.info(
        "%d clips -> %d caption blocks, %d sidecar file(s) -> %s",
        len(doc.clips),
        total_captions,
        len(files),
        out_dir,
        extra={"stage": "captions", "artifact": str(out_dir / "captions.json")},
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "clips": len(doc.clips),
                    "captions": total_captions,
                    "files": files,
                    "caption_version": CAPTION_VERSION,
                    "captions_version": CAPTIONS_VERSION,
                    "input": str(ranking_path),
                    "output": str(out_dir / "captions.json"),
                },
                sort_keys=True,
            )
        )


def _ranking_json_path(path: Path) -> Path:
    """Accept a project dir (containing ranking.json) or a ranking JSON doc."""
    if path.is_dir():
        return path / "ranking.json"
    if not path.is_file():
        raise PipelineError(
            f"ranking input not found: {path}",
            hint="run `clipper rank` first, then `clipper captions RANKING_DIR_OR_JSON`",
        )
    return path


@app.command(help="Compute the 9:16 reframe plan (crop/blur-pad) from analysis.json (Sprint 8).")
@_cmd
def reframe(
    path: Path = typer.Argument(..., help="analysis.json or a scoria project dir"),
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    log_level: str = typer.Option("info", "--log-level", help="debug|info|warning|error"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable summary"),
):
    setup_logging(log_level)
    cfg = build_config(path=config_path, profile=profile)
    if cfg.reframe.mode != "center":
        raise PipelineError(
            f"reframe mode '{cfg.reframe.mode}' is post-MVP (faces/target are roadmap); "
            "MVP accepts only 'center'",
            hint="set reframe.mode: center in the config (or drop --reframe)",
        )
    analysis_path = _analysis_json_path(path)
    analysis = read_json(analysis_path)
    if not isinstance(analysis, dict) or analysis.get("schema") != "analysis":
        raise PipelineError(
            f"not an analysis document (schema != 'analysis'): {analysis_path}",
            hint="run `clipper analyze VID` first, then `clipper reframe <analysis.json>`",
        )
    media = analysis.get("media")
    if not isinstance(media, dict) or media.get("schema") != "media-info":
        raise PipelineError(
            f"analysis has no media section: {analysis_path}",
            hint="run `clipper analyze VID` with a video input (reframe needs width/height)",
        )
    plan = build_reframe_plan(MediaInfo(**media), cfg)
    out_path = write_json(analysis_path.parent / "reframe.json", plan)
    logger.info(
        "%dx%d ar %.4f -> strategy %s -> %s",
        plan.source.width,
        plan.source.height,
        plan.source.aspect_ratio,
        plan.strategy,
        out_path,
        extra={"stage": "reframe", "artifact": str(out_path)},
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "strategy": plan.strategy,
                    "source": normalize(plan.source),
                    "target": normalize(plan.output),
                    "crop": normalize(plan.crop),
                    "content": normalize(plan.content),
                    "pad": normalize(plan.pad),
                    "reframe_version": REFRAME_PLAN_VERSION,
                    "input": str(analysis_path),
                    "output": str(out_path),
                },
                sort_keys=True,
            )
        )


@app.command(help="Print the ScoreBreakdown for one clip (Sprint 10).")
@_cmd
def explain(path: Path, clip_id: str) -> None:
    _not_implemented("explain")


@app.command(help="Write previews + report.html from existing JSON (Sprint 10).")
@_cmd
def report(path: Path) -> None:
    _not_implemented("report")


@app.command(help="Alias for report — previews + timeline strip only (Sprint 10).")
@_cmd
def preview(path: Path) -> None:
    _not_implemented("preview")


@app.command(help="Download + verify the Whisper model (one-time network op).")
@_cmd
def fetch_model(
    config_path: Path | None = typer.Option(None, "-c", "--config", help="YAML config file"),
    profile: str | None = typer.Option(None, "-p", "--profile", help="Config profile"),
    output: Path | None = typer.Option(
        None, "--output", help="Model file path (default transcript.model)"
    ),
):
    from scoria.util.hash import sha256_file

    cfg = build_config(path=config_path, profile=profile)
    model = whisper_model_info(cfg.transcript)["path"]
    if output is not None:
        model = str(Path(output).expanduser())
    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{Path(model).name}"
    err_console.print(f"[cyan]fetching[/cyan] {url}")
    _download_model(url, Path(model))
    sha = sha256_file(Path(model))
    typer.echo(f"downloaded {Path(model)} ({Path(model).stat().st_size} bytes)")
    typer.echo(f"sha256: {sha}")
    typer.echo("set transcript.model_sha256 to that hash to verify every run at startup.")


def _download_model(url: str, target: Path) -> None:
    import urllib.error
    import urllib.request

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(target)
    except urllib.error.URLError as exc:
        tmp.unlink(missing_ok=True)
        raise PipelineError(
            f"model download failed: {exc}", hint="check the network and the model name"
        ) from exc


# ---------------------------------------------------------------------------
# config subcommands (Sprint 0)
# ---------------------------------------------------------------------------


@config_group.command("show")
@_cmd
def config_show() -> None:
    """Print the active (default + discovered config file) config as YAML."""
    typer.echo(dump_yaml(build_config()), nl=False)


@config_group.command("validate")
@_cmd
def config_validate(file: Path) -> None:
    """Validate a YAML config file against the schema."""
    cfg = build_config(path=file)
    typer.echo(f"config ok (version {cfg.version})")


@config_group.command("write-defaults")
@_cmd
def config_write_defaults() -> None:
    """Dump the full default config as YAML."""
    typer.echo(dump_yaml(default_config()), nl=False)


# ---------------------------------------------------------------------------
# verify-env
# ---------------------------------------------------------------------------


@app.command(help="Check tools and versions. Exits 0 if ffmpeg + ffprobe are present.")
@_cmd
def verify_env(
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output"),
):
    report = envcheck.check()
    if json_out:
        typer.echo(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
        return
    typer.echo(envcheck.render_text(report))
    if not report["required_ok"]:
        raise PipelineError(
            "ffmpeg and/or ffprobe not found",
            hint="install ffmpeg (`pacman -S ffmpeg`), then re-run",
        )


# ---------------------------------------------------------------------------
# entry wrapper: `clipper <video> ...` → `clipper run <video> ...`
# ---------------------------------------------------------------------------


def _command_names() -> set[str]:
    def normalize(name: str) -> str:
        return name.replace("_", "-")

    names: set[str] = set()
    for info in app.registered_commands + app.registered_groups:
        if info.name:
            naming = info.name
        else:
            naming = getattr(info.callback, "__name__", None)
        if naming:
            names.add(normalize(naming))
    return names


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] and argv[0][0] != "-" and argv[0] not in _command_names():
        argv = ["run", *argv]
    app(argv or ["--help"])


if __name__ == "__main__":
    main()
