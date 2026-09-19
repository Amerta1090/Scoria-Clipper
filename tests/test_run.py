"""Sprint 11: one-shot `clipper run` — L5 e2e, L4 cross-stage determinism, degraded matrix.

Runs the real pipeline end-to-end on the tiny `planted` fixture (4 s testsrc2+sine,
320×180). STT is never triggered: every invocation passes `--no-transcript` (whisper
is not installed on CI; the real-bridge path is env-gated in test_transcript and the
PRD §8 cold-start runs manually on `sample raw/` captures, TESTING.md §2.1).

Note: `segment.min_duration` (default 20 s) is the clip-length floor and is unrelated
to `media.min_duration` (source validation) — a 4 s fixture needs both lowered here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.ingest.ffprobe import probe
from scoria.util import ffmpeg

runner = CliRunner()

OUT = (1080, 1920)

# Sprint 13 (ADR-021): offline transcript-info doc — same 18 words as the
# whisper golden; a run pointed at it never touches an STT binary.
TRANSCRIPT_INFO = Path(__file__).parent / "fixtures" / "transcript_info.json"

_RUN_CFG_YAML = (
    "media:\n"
    "  min_duration: 1.0\n"
    "audio:\n"
    "  silence:\n"
    "    min_duration: 0.1\n"
    "segment:\n"
    "  min_duration: 1.0\n"
    "  max_duration: 2.5\n"
    "  preferred:\n"
    "    min: 1.5\n"
    "    max: 2.5\n"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(path: Path, project: Path) -> str:
    """Hash with the project dir normalized out (artifacts embed their output path).

    Two runs land in different directories, so byte comparison is only meaningful
    with the project location normalized to a placeholder.
    """
    data = path.read_bytes().replace(str(project).encode(), b"<proj>")
    return hashlib.sha256(data).hexdigest()


def _video_dims(path: Path) -> tuple[int, int]:
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return video["width"], video["height"]


def _json(project: Path, name: str) -> dict:
    return json.loads((project / name).read_text(encoding="utf-8"))


def _run_cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "run.yaml"
    cfg.write_text(_RUN_CFG_YAML, encoding="utf-8")
    return cfg


def _transcript_run_cfg(tmp_path: Path) -> Path:
    """Sprint 13: add `transcript.path` → offline ingest, no STT binary needed."""
    cfg = tmp_path / "run.yaml"
    cfg.write_text(_RUN_CFG_YAML + f"transcript:\n  path: {TRANSCRIPT_INFO}\n", encoding="utf-8")
    return cfg


def _run_args(video: Path, cfg: Path, out: Path, *extra: str) -> list[str]:
    return ["run", str(video), "-o", str(out), "-c", str(cfg), "--log-level", "error", *extra]


def _artifact_spec(project: Path) -> dict[str, Path]:
    return {
        "analysis": project / "analysis.json",
        "candidates": project / "candidates.json",
        "ranking": project / "ranking.json",
        "reframe": project / "reframe.json",
        "render": project / "render.json",
        "manifest": project / "manifest.json",
        "previews": project / "previews" / "previews.json",
        "report": project / "report.html",
    }


# ---------------------------------------------------------------------------
# L5 e2e: one-shot run
# ---------------------------------------------------------------------------


def test_run_e2e_full_chain(tmp_path, planted):
    out = tmp_path / "proj"
    cfg = _run_cfg(tmp_path)
    result = runner.invoke(app, _run_args(planted, cfg, out, "--no-transcript", "--no-visual"))
    assert result.exit_code == 0, result.output
    for name, path in _artifact_spec(out).items():
        assert path.is_file(), f"{name} missing: {path}"
    analysis = _json(out, "analysis.json")
    assert analysis["schema"] == "analysis"
    assert analysis.get("transcript") is None and analysis.get("visual") is None

    candidates = _json(out, "candidates.json")
    assert len(candidates["candidates"]) >= 1

    ranking = _json(out, "ranking.json")
    assert 1 <= len(ranking["selected"]) <= 3

    # no transcript words on this fixture → burn degrades (never silent)
    render = _json(out, "render.json")
    assert render["burn"] is False
    assert "captions_unavailable" in render["degraded"]

    clips = sorted((out / "clips").glob("*.mp4"))
    assert len(clips) == len(ranking["selected"])
    assert all(_video_dims(clip) == OUT for clip in clips)

    html = (out / "report.html").read_text(encoding="utf-8")
    assert "<html" in html.lower()
    previews = _json(out, "previews/previews.json")
    assert len(previews["clips"]) == len(ranking["selected"])


def test_run_json_summary(tmp_path, planted):
    out = tmp_path / "proj"
    cfg = _run_cfg(tmp_path)
    result = runner.invoke(
        app,
        _run_args(planted, cfg, out, "--no-transcript", "--no-visual", "--json"),
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["ok"] is True
    assert summary["selected"] >= 1 and summary["rendered"] == summary["selected"]
    assert summary["degraded"] == ["transcript", "visual", "captions_unavailable"]
    assert summary["project"] == str(out)


# ---------------------------------------------------------------------------
# Sprint 11 degraded-mode matrix (TESTING.md §5): never crashes, never silent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "null_sections", "render_degraded"),
    [
        (("--no-transcript",), ("transcript",), ["captions_unavailable"]),
        (
            ("--no-transcript", "--no-visual"),
            ("transcript", "visual"),
            ["captions_unavailable"],
        ),
    ],
)
def test_run_degraded_matrix(tmp_path, planted, flags, null_sections, render_degraded):
    out = tmp_path / "proj"
    cfg = _run_cfg(tmp_path)
    result = runner.invoke(app, _run_args(planted, cfg, out, *flags))
    assert result.exit_code == 0, result.output
    analysis = _json(out, "analysis.json")
    for section in null_sections:
        assert analysis.get(section) is None, f"{section} should be null"
    candidates = _json(out, "candidates.json")
    assert len(candidates["candidates"]) >= 1
    render = _json(out, "render.json")
    assert render["burn"] is False
    assert [flag for flag in render_degraded if flag in render["degraded"]] == render_degraded


def test_run_no_captions_skips_caption_work(tmp_path, planted):
    out = tmp_path / "proj"
    cfg = _run_cfg(tmp_path)
    result = runner.invoke(app, _run_args(planted, cfg, out, "--no-transcript", "--no-captions"))
    assert result.exit_code == 0, result.output
    render = _json(out, "render.json")
    assert render["burn"] is False
    assert not (out / "captions").exists()
    assert not any(m in render["degraded"] for m in ("captions_unavailable", "burn_sidecar_only"))


# ---------------------------------------------------------------------------
# L4: cross-stage determinism (SPRINT_PLANNING §S11, TESTING.md §4)
# ---------------------------------------------------------------------------


def test_run_deterministic_cross_stage(tmp_path, planted):
    """Same inputs + config → byte-identical artifacts across two full runs."""
    cfg = _run_cfg(tmp_path)
    outs = [tmp_path / "run_a", tmp_path / "run_b"]
    specs = []
    for out in outs:
        result = runner.invoke(app, _run_args(planted, cfg, out, "--no-transcript", "--no-visual"))
        assert result.exit_code == 0, result.output
        specs.append(_artifact_spec(out))

    # JSON + HTML corpus is byte-stable (project location normalized out)
    hashes = [
        {name: _stable_hash(path, out) for name, path in spec.items()}
        for spec, out in zip(specs, outs, strict=True)
    ]
    assert set(hashes[0]) == set(hashes[1])
    for name in hashes[0]:
        assert hashes[0][name] == hashes[1][name], f"{name} differs between runs"

    # rendered clip streams are byte-identical too (pinned ffmpeg args)
    clips_a = sorted((outs[0] / "clips").glob("*.mp4"))
    clips_b = sorted((outs[1] / "clips").glob("*.mp4"))
    assert [p.name for p in clips_a] == [p.name for p in clips_b]
    for pa, pb in zip(clips_a, clips_b, strict=True):
        assert _sha256(pa) == _sha256(pb), f"clip stream differs: {pa.name}"


# ---------------------------------------------------------------------------
# Sprint 12: gamer two-zone reframe through the one-shot run
# ---------------------------------------------------------------------------


def test_run_gamer_profile_two_zone_clips(tmp_path, planted):
    """`clipper run X --profile gaming` → two-zone reframe + 1080×1920 clips."""
    out = tmp_path / "gamer_proj"
    cfg = _run_cfg(tmp_path)
    result = runner.invoke(
        app, _run_args(planted, cfg, out, "--profile", "gaming", "--no-transcript", "--no-visual")
    )
    assert result.exit_code == 0, result.output
    reframe = _json(out, "reframe.json")
    assert reframe["layout"] == "gamer" and reframe["strategy"] is None
    zones = reframe["zones"]
    assert [z["role"] for z in zones] == ["gameplay", "facecam"]
    assert sum(z["height"] for z in zones) == reframe["output"]["height"]
    assert all(z["width"] == reframe["output"]["width"] for z in zones)
    clips = sorted((out / "clips").glob("*.mp4"))
    assert clips, "gamer run produced no clips"
    assert all(_video_dims(clip) == OUT for clip in clips)
    render = _json(out, "render.json")
    assert all("vstack=inputs=2" in c["filters"] for c in render["clips"])


def test_run_gamer_deterministic_cross_stage(tmp_path, planted):
    """L4 gaming variant: two gamer runs → byte-identical corpus + clip streams."""
    cfg = _run_cfg(tmp_path)
    outs = [tmp_path / "gamer_a", tmp_path / "gamer_b"]
    specs = []
    for out in outs:
        result = runner.invoke(
            app,
            _run_args(planted, cfg, out, "--profile", "gaming", "--no-transcript", "--no-visual"),
        )
        assert result.exit_code == 0, result.output
        specs.append(_artifact_spec(out))

    hashes = [
        {name: _stable_hash(path, out) for name, path in spec.items()}
        for spec, out in zip(specs, outs, strict=True)
    ]
    for name in hashes[0]:
        assert hashes[0][name] == hashes[1][name], f"{name} differs between gamer runs"

    clips_a = sorted((outs[0] / "clips").glob("*.mp4"))
    clips_b = sorted((outs[1] / "clips").glob("*.mp4"))
    assert [p.name for p in clips_a] == [p.name for p in clips_b]
    for pa, pb in zip(clips_a, clips_b, strict=True):
        assert _sha256(pa) == _sha256(pb), f"gamer clip stream differs: {pa.name}"


# ---------------------------------------------------------------------------
# Sprint 13: captions-on run fed by `transcript.path` (ADR-021) — never STT
# ---------------------------------------------------------------------------


def test_run_transcript_path_captions_burn(tmp_path, planted):
    """Offline transcript → scoring signal, caption sidecars, and (libass) burn."""
    out = tmp_path / "proj"
    cfg = _transcript_run_cfg(tmp_path)
    result = runner.invoke(app, _run_args(planted, cfg, out, "--no-visual"))
    assert result.exit_code == 0, result.output

    transcript = _json(out, "analysis.json")["transcript"]
    assert transcript["schema"] == "transcript-info"
    assert transcript["word_count"] == 18
    assert [s["text"] for s in transcript["sentences"]] == [
        "Apakah kalian tahu cara membuat konten?",
        "Viral di tiktok, tanpa effort.",
        "Rahasia cuma satu sip.",
        "Dan itu saja.",
    ]

    assert _json(out, "manifest.json")["transcript_source"] == "file"

    # caption sidecars were built from the offline transcript words
    cap_dir = out / "captions"
    assert sorted(p.name for p in cap_dir.glob("*.srt")), "no SRT sidecars"
    assert sorted(p.name for p in cap_dir.glob("*.ass")), "no ASS sidecars"
    assert (cap_dir / "captions.json").is_file()

    render = _json(out, "render.json")
    if ffmpeg.has_filter("subtitles"):
        assert render["burn"] is True
        assert "captions_unavailable" not in render["degraded"]
        assert "burn_sidecar_only" not in render["degraded"]
    else:
        assert render["burn"] is False
        assert "burn_sidecar_only" in render["degraded"]

    clips = sorted((out / "clips").glob("*.mp4"))
    assert clips, "captions run produced no clips"
    assert all(_video_dims(clip) == OUT for clip in clips)


def test_run_transcript_path_deterministic_cross_stage(tmp_path, planted):
    """L4 captions variant: two file-transcript runs → byte-identical corpus + clips."""
    cfg = _transcript_run_cfg(tmp_path)
    outs = [tmp_path / "cap_a", tmp_path / "cap_b"]
    specs = []
    for out in outs:
        result = runner.invoke(app, _run_args(planted, cfg, out, "--no-visual"))
        assert result.exit_code == 0, result.output
        specs.append(_artifact_spec(out))

    hashes = [
        {name: _stable_hash(path, out) for name, path in spec.items()}
        for spec, out in zip(specs, outs, strict=True)
    ]
    assert set(hashes[0]) == set(hashes[1])
    for name in hashes[0]:
        assert hashes[0][name] == hashes[1][name], f"{name} differs between captions runs"

    # caption documents + sidecars are part of the deterministic corpus
    caps_a = sorted((outs[0] / "captions").iterdir())
    caps_b = sorted((outs[1] / "captions").iterdir())
    assert [p.name for p in caps_a] == [p.name for p in caps_b]
    for pa, pb in zip(caps_a, caps_b, strict=True):
        assert _sha256(pa) == _sha256(pb), f"caption artifact differs: {pa.name}"

    clips_a = sorted((outs[0] / "clips").glob("*.mp4"))
    clips_b = sorted((outs[1] / "clips").glob("*.mp4"))
    assert [p.name for p in clips_a] == [p.name for p in clips_b]
    for pa, pb in zip(clips_a, clips_b, strict=True):
        assert _sha256(pa) == _sha256(pb), f"clip stream differs: {pa.name}"
