"""CLI entry point: `clipper` console script.

One-shot `clipper <video> [OPTIONS]` is handled by the entry wrapper in `main()`,
which rewrites it into the `run` subcommand (CLI_SPEC.md §1); `run` shares the flag
set with the top-level invocation. Pipeline stages are registered stubs whose help
matches CLI_SPEC.md; running them raises PipelineError (exit 1). `config` (Sprint 0)
and `verify-env` are functional.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from scoria import envcheck
from scoria.config import build_config, default_config, dump_yaml
from scoria.errors import PipelineError, ScoriaError
from scoria.util.logging import setup_logging

err_console = Console(stderr=True, highlight=False)


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


@app.command(help="Produce analysis.json (Sprint 1).")
@_cmd
def analyze(video: Path) -> None:
    _not_implemented("analyze")


@app.command(help="Produce raw candidates.json from analysis (Sprint 4).")
@_cmd
def segment(path: Path) -> None:
    _not_implemented("segment")


@app.command(help="Score candidates.json (Sprint 5).")
@_cmd
def score(path: Path) -> None:
    _not_implemented("score")


@app.command(help="Rank candidates.json to top-N (Sprint 6).")
@_cmd
def rank(path: Path) -> None:
    _not_implemented("rank")


@app.command(help="Render ranking.json → clips/ + captions/ (Sprint 9).")
@_cmd
def render(path: Path) -> None:
    _not_implemented("render")


@app.command(help="Write SRT + ASS only from ranking.json (Sprint 7).")
@_cmd
def captions(path: Path) -> None:
    _not_implemented("captions")


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


@app.command(help="One-time model download (Sprint 3).")
@_cmd
def fetch_model() -> None:
    _not_implemented("fetch-model")


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
