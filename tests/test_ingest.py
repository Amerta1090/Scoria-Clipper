"""L1/L5: ingestion — ffprobe probing, stream selection, validation, analysis.json.media.

Fixtures are tiny lavfi-generated mp4/m4a files (deterministic by construction,
TESTING.md §2). No network, no copyrighted media.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.errors import MediaError, PipelineError
from scoria.ingest import analyze_video, build_media, probe, select_video_stream
from scoria.project import check_contract, dump_str

runner = CliRunner()
REPO_ROOT = Path(__file__).parent.parent


def _cfg(**overrides):
    data = {"media": {"min_duration": 1.0}}
    data.update(overrides)
    return build_config(overrides=data)


# ---------------------------------------------------------------------------
# ffprobe wrapper / stream selection
# ---------------------------------------------------------------------------


def test_probe_returns_format_and_streams(landscape):
    data = probe(str(landscape))
    assert data["format"]["format_name"]
    kinds = {s["codec_type"] for s in data["streams"]}
    assert kinds == {"video", "audio"}


def test_auto_selects_first_video_stream(landscape):
    data = probe(str(landscape))
    index, stream = select_video_stream(data["streams"], "auto")
    assert index == 0
    assert stream["codec_type"] == "video"


def test_explicit_index_selects_same_stream(landscape):
    data = probe(str(landscape))
    index, stream = select_video_stream(data["streams"], 0)
    assert (index, stream) == select_video_stream(data["streams"], "auto")


def test_explicit_index_out_of_range(landscape):
    data = probe(str(landscape))
    with pytest.raises(MediaError, match="out of range"):
        select_video_stream(data["streams"], 5)


def test_explicit_audio_index_rejected(landscape):
    data = probe(str(landscape))
    with pytest.raises(MediaError, match="not video"):
        select_video_stream(data["streams"], 1)


def test_no_video_stream_is_actionable(audio_only):
    with pytest.raises(MediaError, match="no video stream"):
        build_media(audio_only, _cfg(), source=str(audio_only), source_kind="file")


def test_probe_missing_file_is_actionable(tmp_path):
    missing = tmp_path / "nope.mp4"
    with pytest.raises(MediaError, match="cannot probe"):
        probe(str(missing))


# ---------------------------------------------------------------------------
# build_media: dimensions / AR / duration / timebase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "expected_w", "expected_h", "expected_ar"),
    [
        ("landscape", 640, 360, 16 / 9),
        ("portrait", 360, 640, 9 / 16),
        ("classic", 640, 480, 4 / 3),
    ],
)
def test_media_contract_dimensions_ar(fixture, expected_w, expected_h, expected_ar, request):
    path = request.getfixturevalue(fixture)
    media = build_media(path, _cfg(), source=path.name, source_kind="file")
    assert media.width == expected_w
    assert media.height == expected_h
    assert media.aspect_ratio == pytest.approx(expected_ar, rel=1e-4)
    assert media.stream_index == 0
    assert media.codec == "h264" or media.codec is not None
    assert media.pixel_format
    assert media.time_base
    assert media.container
    assert media.analysis.start == 0.0
    assert media.analysis.end == pytest.approx(media.duration, abs=0.25)
    assert media.duration == pytest.approx(3.0, abs=0.25)


def test_media_contract_serializes_clean(tmp_path, landscape):
    media = build_media(landscape, _cfg(), source="landscape.mp4", source_kind="file")
    raw = json.loads(dump_str(media))
    assert check_contract(raw) == []
    assert raw["schema"] == "media-info"
    # timestamps normalized to seconds (not rationals)
    assert isinstance(raw["duration"], float)
    assert isinstance(raw["start_time"], float)
    assert raw["aspect_ratio"] == round(16 / 9, 4)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_duration_below_min_is_error(landscape):
    cfg = build_config()  # default media.min_duration = 8.0 vs a 3s fixture
    with pytest.raises(MediaError, match="media.min_duration"):
        build_media(landscape, cfg, source="landscape.mp4", source_kind="file")


def test_analysis_window_slicing(landscape):
    cfg = _cfg(audio={"analyze_start": 0.5, "analyze_end": 2.5})
    media = build_media(landscape, cfg, source="landscape.mp4", source_kind="file")
    assert media.analysis.start == 0.5
    assert media.analysis.end == 2.5


def test_analysis_window_end_beyond_duration_is_error(landscape):
    cfg = _cfg(audio={"analyze_end": 99.0})
    with pytest.raises(MediaError, match="audio.analyze_end"):
        build_media(landscape, cfg, source="landscape.mp4", source_kind="file")


def test_analysis_window_start_beyond_duration_is_error(landscape):
    cfg = _cfg(audio={"analyze_start": 99.0})
    with pytest.raises(MediaError, match="audio.analyze_start"):
        build_media(landscape, cfg, source="landscape.mp4", source_kind="file")


# ---------------------------------------------------------------------------
# analyze_video: analysis.json + project dir semantics
# ---------------------------------------------------------------------------


def test_analyze_video_writes_analysis_json(tmp_path, landscape):
    project = tmp_path / "proj"
    cfg = build_config(
        overrides={
            "project": {"dir": str(project)},
            "media": {"min_duration": 1.0},
            "transcript": {"enabled": False},
        }
    )
    media, project_dir, degraded = analyze_video(str(landscape), cfg)
    assert project_dir == project
    assert degraded == ["transcript"]
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["schema"] == "analysis"
    assert analysis["media"]["width"] == media.width == 640
    assert analysis["media"]["source"] == str(landscape)
    assert analysis["transcript"] is None
    assert check_contract(analysis) == []


def test_analyze_video_refuses_existing_dir(tmp_path, landscape):
    project = tmp_path / "proj"
    cfg = build_config(
        overrides={
            "project": {"dir": str(project)},
            "media": {"min_duration": 1.0},
            "transcript": {"enabled": False},
        }
    )
    analyze_video(str(landscape), cfg)
    with pytest.raises(PipelineError, match="already exists"):
        analyze_video(str(landscape), cfg)


def test_analyze_deterministic_two_runs(tmp_path, landscape):
    project = tmp_path / "proj"
    cfg = build_config(
        overrides={
            "project": {"dir": str(project), "overwrite": True},
            "media": {"min_duration": 1.0},
            "transcript": {"enabled": False},
        }
    )
    analyze_video(str(landscape), cfg)
    first = (project / "analysis.json").read_bytes()
    analyze_video(str(landscape), cfg)
    assert (project / "analysis.json").read_bytes() == first


# ---------------------------------------------------------------------------
# stdin
# ---------------------------------------------------------------------------


def test_spool_stream_from_bytesio(tmp_path):
    target = tmp_path / "spool.bin"
    from io import BytesIO

    from scoria.ingest import spool_stream

    spool_stream(target, BytesIO(b"\x00\x01\x02"))
    assert target.read_bytes() == b"\x00\x01\x02"


def test_analyze_stdin_via_cli(tmp_path, landscape, min_cfg):
    project = tmp_path / "stdin_proj"
    cmd = [
        sys.executable,
        "-m",
        "scoria.cli",
        "analyze",
        "-",
        "-o",
        str(project),
        "-c",
        str(min_cfg),
        "--no-transcript",
        "--overwrite",
    ]
    proc = subprocess.run(
        cmd,
        input=landscape.read_bytes(),
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["media"]["source"] == "-"
    assert analysis["media"]["source_kind"] == "stdin"
    assert analysis["media"]["width"] == 640
    assert analysis["media"]["height"] == 360


def test_analyze_stdin_requires_output_dir():
    result = runner.invoke(app, ["analyze", "-"])
    assert result.exit_code == 2
    assert "project dir" in result.output.lower() or "output" in result.output.lower()


def test_analyze_stdin_empty_is_error(tmp_path):
    project = tmp_path / "empty_proj"
    result = runner.invoke(
        app,
        ["analyze", "-", "-o", str(project), "--overwrite", "--log-level", "error"],
        input=b"",
    )
    assert result.exit_code == 1
    assert "no bytes" in result.output


# ---------------------------------------------------------------------------
# CLI: analyze command surface
# ---------------------------------------------------------------------------


def test_cli_analyze_exit_zero_writes_manifest(tmp_path, landscape, min_cfg):
    project = tmp_path / "proj"
    result = runner.invoke(
        app,
        ["analyze", str(landscape), "-o", str(project), "-c", str(min_cfg), "--no-transcript"],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "project-manifest"
    assert manifest["tools"]["ffmpeg"]["version"]
    assert manifest["degraded"] == ["transcript"]
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["media"]["duration"] > 0
    assert analysis["transcript"] is None


def test_cli_analyze_json_summary(tmp_path, landscape, min_cfg):
    project = tmp_path / "proj"
    result = runner.invoke(
        app,
        [
            "analyze",
            str(landscape),
            "-o",
            str(project),
            "-c",
            str(min_cfg),
            "--no-transcript",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.strip().splitlines()[-1])
    assert summary["media"]["width"] == 640
    assert summary["media"]["aspect_ratio"] == round(16 / 9, 4)
    assert summary["analysis"].endswith("analysis.json")
    assert summary["transcript"] is None


def test_cli_analyze_overwrite_guard(tmp_path, landscape, min_cfg):
    project = tmp_path / "proj"
    args = ["analyze", str(landscape), "-o", str(project), "-c", str(min_cfg), "--no-transcript"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0
    second = runner.invoke(app, args)
    assert second.exit_code == 1
    assert "project dir" in second.output.lower()
    assert "overwrite" in second.output.lower()


def test_cli_analyze_deterministic(tmp_path, landscape, min_cfg):
    project = tmp_path / "proj"
    args = [
        "analyze",
        str(landscape),
        "-o",
        str(project),
        "-c",
        str(min_cfg),
        "--no-transcript",
        "--overwrite",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    first_analysis = (project / "analysis.json").read_bytes()
    first_manifest = (project / "manifest.json").read_bytes()
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert (project / "analysis.json").read_bytes() == first_analysis
    assert (project / "manifest.json").read_bytes() == first_manifest
