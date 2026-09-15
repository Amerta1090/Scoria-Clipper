"""Sprint 4: visual scene detection — scdet stderr parsing, threshold mapping, and
the real ffmpeg pass over a deterministic hard-cut video (testsrc2 → smptebars).

L0 tests cover the pure stderr parser; the module-scoped `cut_video` fixture (two
2 s lavfi sources at a hard edit point) exercises the actual scdet run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoria.config import build_config
from scoria.ingest import analyze_video
from scoria.util.ffmpeg import run_ffmpeg
from scoria.visual import VISUAL_SCHEMA
from scoria.visual.scene import detect_scenes, parse_scd_stderr, scdet_threshold_percent

FIXTURES = Path(__file__).parent / "fixtures"


def _cfg(**overrides):
    data = {"media": {"min_duration": 1.0}}
    data.update(overrides)
    return build_config(overrides=data)


# ---------------------------------------------------------------------------
# L0: pure stderr parser
# ---------------------------------------------------------------------------


def test_parse_scd_stderr_extracts_and_normalizes():
    stderr = (
        "ffmpeg version n9.0.1\n"
        "[Parsed_scdet_3 @ 0x556a] lavfi.scd.score: 99.609, lavfi.scd.time: 2\n"
        "noise: [Parsed_scdet_3] lavfi.scd.score: 44.080, lavfi.scd.time: 4.25\n"
        "Output #0, null,\n"
    )
    parsed = parse_scd_stderr(stderr)
    assert [(t, s) for t, s in parsed] == [
        (2.0, pytest.approx(0.99609, abs=1e-6)),
        (4.25, pytest.approx(0.4408, abs=1e-6)),
    ]


def test_parse_scd_stderr_dedupes_same_time_and_sorts():
    stderr = (
        "lavfi.scd.score: 51.9, lavfi.scd.time: 4\n"
        "lavfi.scd.score: 42.9, lavfi.scd.time: 4\n"  # duplicate time
        "lavfi.scd.score: 49.5, lavfi.scd.time: 2\n"
    )
    assert parse_scd_stderr(stderr) == [
        (2.0, pytest.approx(0.495, abs=1e-6)),
        (4.0, pytest.approx(0.519, abs=1e-6)),
    ]


def test_parse_scd_stderr_empty_and_noise_only():
    assert parse_scd_stderr("") == []
    assert parse_scd_stderr("[Parsed_scdet_3 @ 0x1] nothing to see") == []


def test_scdet_threshold_percent_mapping():
    assert scdet_threshold_percent(0.35) == 35
    assert scdet_threshold_percent(1.0) == 100
    assert scdet_threshold_percent(0.0) == 0


# ---------------------------------------------------------------------------
# L1: real scdet pass over a hard-cut video
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cut_video(_media_dir):
    """Black (2 s) → white (2 s): a maximal-luminance hard cut at t=2.0."""
    path = _media_dir / "scene_cut_bw.mp4"
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=320x180:r=10:d=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[out]",
            "-map",
            "[out]",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            str(path),
        ]
    )
    return path


def test_detect_scenes_finds_hard_cut(cut_video):
    info = detect_scenes(cut_video, start=0.0, end=4.0, fps=4, width=64, height=36, threshold=0.35)
    assert info.scene_count >= 1
    assert all(0.0 <= scene.score <= 1.0 for scene in info.scenes)
    assert any(abs(scene.time - 2.0) <= 0.51 for scene in info.scenes)
    assert info.fps == 4
    assert info.threshold == 0.35


def test_detect_scenes_deterministic(cut_video):
    kwargs = dict(start=0.0, end=4.0, fps=4, width=64, height=36, threshold=0.35)
    first = detect_scenes(cut_video, **kwargs)
    second = detect_scenes(cut_video, **kwargs)
    assert [(s.time, s.score) for s in first.scenes] == [(s.time, s.score) for s in second.scenes]


def test_detect_scenes_max_threshold_finds_nothing(cut_video):
    info = detect_scenes(cut_video, start=0.0, end=4.0, fps=4, width=64, height=36, threshold=1.0)
    assert info.scene_count == 0


# ---------------------------------------------------------------------------
# L1/L2: analyze_visual + analyze_video wiring
# ---------------------------------------------------------------------------


def test_analyze_visual_disabled(tmp_path):
    from scoria.visual import analyze_visual

    info, degraded = analyze_visual(
        tmp_path / "in.mp4", _cfg(visual={"enabled": False}), _media_config_stub()
    )
    assert info is None
    assert degraded == ["visual"]


def _media_config_stub():
    from scoria.ingest.models import AnalysisWindow, MediaInfo

    return MediaInfo(
        schema="media-info",
        source="in.mp4",
        source_kind="file",
        container="mp4",
        stream_index=0,
        codec="h264",
        width=320,
        height=180,
        pixel_format="yuv420p",
        duration=4.0,
        start_time=0.0,
        time_base="1/1000",
        avg_frame_rate="10/1",
        frame_count=40,
        aspect_ratio=16 / 9,
        display_aspect_ratio="16:9",
        rotation=0.0,
        analysis=AnalysisWindow(start=0.0, end=4.0),
    )


def test_analyze_video_writes_visual_section(tmp_path, planted):
    project = tmp_path / "proj"
    cfg = _cfg(project={"dir": str(project)}, transcript={"enabled": False})
    _, _, degraded = analyze_video(str(planted), cfg)
    assert degraded == ["transcript"]
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    visual = analysis["visual"]
    assert visual["schema"] == VISUAL_SCHEMA
    assert visual["fps"] == 4
    assert visual["threshold"] == 0.35
    assert isinstance(visual["scenes"], list)


def test_analyze_video_no_visual_is_degraded(tmp_path, planted):
    project = tmp_path / "proj"
    cfg = _cfg(
        project={"dir": str(project)},
        transcript={"enabled": False},
        visual={"enabled": False},
    )
    _, _, degraded = analyze_video(str(planted), cfg)
    assert degraded == ["transcript", "visual"]
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["visual"] is None


def test_analyze_video_visual_deterministic(tmp_path, planted):
    project = tmp_path / "proj"
    cfg = _cfg(project={"dir": str(project), "overwrite": True}, transcript={"enabled": False})
    analyze_video(str(planted), cfg)
    first = (project / "analysis.json").read_bytes()
    analyze_video(str(planted), cfg)
    assert (project / "analysis.json").read_bytes() == first
