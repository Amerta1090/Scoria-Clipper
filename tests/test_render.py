"""Sprint 9: render — pure graph/gain math, CLI flags, L3 ffprobe e2e.

L0 pins the filter-graph builders (`build_video_chain`, `with_burn`, path
escaping), the ADR-005 static-gain math and the deterministic ffmpeg arg
surface; L5 pins `clipper render` (auto-reframe, skip/exists/--force, burn vs
`--no-burn`, degraded stamps, CRF/preset overrides, error exits); L3 renders a
tiny testsrc2+sine fixture through the real graph and asserts 1080×1920, ±100 ms
duration, h264+aac streams via ffprobe (Sprint 9 DoD).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.ingest import MediaInfo
from scoria.ingest.ffprobe import probe
from scoria.project import check_contract, dump_str, write_json
from scoria.reframe import build_reframe_plan, plan_for_dims
from scoria.render.core import _clip_args
from scoria.render.graph import audio_gain_db, build_video_chain, escape_filter_path, with_burn
from scoria.util import ffmpeg

runner = CliRunner()

OUT = (1080, 1920)

ASS_FIXTURE = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,"
    "0,0,1,3,0,2,40,40,80,1\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:00.20,0:00:00.60,Default,,0,0,0,,HELLO\n"
)


def _clip(**overrides) -> dict:
    clip = {
        "id": "c0001",
        "rank": 1,
        "start": 0.5,
        "end": 1.3,
        "duration": 0.8,
        "score": 60.0,
        "gain": 0.0,
        "gain_note": "test",
        "overlap_seconds": 0.0,
        "overlap_penalty": 0.0,
        "jaccard_max": 0.0,
        "sim_penalty": 0.0,
        "gap": None,
        "gap_penalty": 0.0,
    }
    clip.update(overrides)
    return clip


# ---------------------------------------------------------------------------
# L0: audio gain (ADR-005)
# ---------------------------------------------------------------------------


def test_audio_gain_db_no_measurement_is_passthrough():
    assert audio_gain_db(None, target_lufs=-16.0, target_peak=-1.5) == 0.0


def test_audio_gain_db_raises_to_target():
    assert audio_gain_db(-22.0, target_lufs=-16.0, target_peak=-1.5) == 6.0
    assert audio_gain_db(-10.0, target_lufs=-16.0, target_peak=-1.5) == -6.0


def test_audio_gain_db_capped_by_peak_headroom():
    # raising +4 dB would push true peak -0.5 → +3.5; cap at target_peak -1.5.
    assert audio_gain_db(-20.0, target_lufs=-16.0, target_peak=-1.5, measured_peak=-0.5) == -1.0


# ---------------------------------------------------------------------------
# L0: filter graph (pure)
# ---------------------------------------------------------------------------


def test_build_video_chain_crop_16x9():
    plan = plan_for_dims(640, 360, build_config().reframe)
    assert plan.strategy == "crop"
    fc, vf, label = build_video_chain(plan)
    assert fc is None and label is None
    assert vf == "crop=202:360:220:0,scale=1080:1920"


def test_build_video_chain_scale_exact_9x16():
    plan = plan_for_dims(1080, 1920, build_config().reframe)
    assert plan.strategy == "scale"
    fc, vf, label = build_video_chain(plan)
    assert fc is None and label is None and vf == "scale=1080:1920"


def test_build_video_chain_blur_pad_21x9():
    plan = plan_for_dims(2560, 1080, build_config().reframe)
    assert plan.strategy == "blur_pad"
    fc, vf, label = build_video_chain(plan)
    assert vf is None and label == "[vout]"
    assert "split=2[bg][fg]" in fc
    assert "[bg]scale=1080:1920,boxblur=20:4[bg2]" in fc
    assert "[fg]scale=1080:456[fg2]" in fc
    assert "[bg2][fg2]overlay=0:732[vout]" in fc


def test_with_burn_vf_and_complex():
    plan = plan_for_dims(640, 360, build_config().reframe)
    fc, vf, label = build_video_chain(plan)
    fc2, vf2, label2 = with_burn(fc, vf, label, Path("/tmp/out dir/c0001.ass"))
    assert fc2 is None and label2 is None
    assert vf2.startswith("crop=")
    # Deterministic surface (S9 DoD): `escape_filter_path` escapes only the
    # ffmpeg filter specials (`: , ' [ ]`) and carries spaces through raw —
    # same keyed-clip subtitles surface asserted in L0/L5/L3.
    assert "subtitles=filename=/tmp/out dir/c0001.ass" in vf2

    blur = plan_for_dims(2560, 1080, build_config().reframe)
    fc, vf, label = build_video_chain(blur)
    fc2, vf2, label2 = with_burn(fc, vf, label, Path("/tmp/c0001.ass"))
    assert vf2 is None and label2 == "[vout2]"
    assert fc2.endswith("[vout]subtitles=filename=/tmp/c0001.ass[vout2]")


# ---------------------------------------------------------------------------
# Sprint 12 L0: gamer vstack composite
# ---------------------------------------------------------------------------


def test_build_video_chain_gamer():
    cfg = build_config(profile="gaming")
    plan = plan_for_dims(1920, 1080, cfg.reframe)
    assert plan.layout == "gamer"
    fc, vf, label = build_video_chain(plan)
    assert vf is None and label == "[vout]"
    assert fc == (
        "[0:v]split=2[game][cam];"
        "[game]crop=1012:1080:454:0,scale=1080:1152,setsar=1[game2];"
        "[cam]crop=304:216:1144:842,scale=1080:768,setsar=1[cam2];"
        "[game2][cam2]vstack=inputs=2[vout]"
    )


def test_with_burn_gamer_composite():
    cfg = build_config(profile="gaming")
    plan = plan_for_dims(1920, 1080, cfg.reframe)
    fc, vf, label = build_video_chain(plan)
    fc2, vf2, label2 = with_burn(fc, vf, label, Path("/tmp/c0001.ass"))
    assert vf2 is None and label2 == "[vout2]"
    assert fc2.endswith("[vout]subtitles=filename=/tmp/c0001.ass[vout2]")


def test_build_video_chain_gamer_degenerate_single_zone():
    # Out-of-contract degenerate plan (zone list of one, from compute_gamer_zones
    # on a <2×2 source) falls back to the plain scale path — totality, not a
    # real-media path (ffprobe dims are ≥ 2 by contract).
    plan = plan_for_dims(1920, 1080, build_config(profile="gaming").reframe)
    plan = plan.model_copy(update={"zones": [plan.zones[0]]})
    fc, vf, label = build_video_chain(plan)
    assert fc is None and label is None and vf == "scale=1080:1920"


def test_escape_filter_path():
    assert escape_filter_path(Path("/a b/c.ass")) == "/a b/c.ass"
    assert escape_filter_path(Path("/p:1/q,2'[x].ass")) == "/p\\:1/q\\,2\\'\\[x\\].ass"


def test_clip_args_pinned_and_deterministic(tmp_path):
    cfg = build_config()
    plan = plan_for_dims(640, 360, cfg.reframe)
    clip = _clip()
    base = dict(
        clip=clip,
        source="/src/video.mp4",
        plan=plan,
        cfg=cfg,
        gain_db=2.5,
        ass_path=None,
        out_path=tmp_path / "c0001.mp4",
        crf=19,
        preset="medium",
        has_audio=True,
        burn=False,
    )
    args1, filters, burned1 = _clip_args(**base)
    args2, filters2, burned2 = _clip_args(**base)
    assert args1 == args2 and filters == filters2 and burned1 == burned2 is False
    assert args1[0] == "-ss" and args1[2] == "-t"
    joined = " ".join(args1)
    assert "-nostdin" not in joined  # pinned by run_ffmpeg
    assert "-threads 4" in joined
    assert "-c:v libx264" in joined and "-crf 19" in joined and "-preset medium" in joined
    assert "-pix_fmt yuv420p" in joined and "-movflags +faststart" in joined
    assert "-map 0:v:0" in joined and "-map 0:a:0" in joined and "-c:a aac" in joined
    assert "volume=2.5dB" in joined and joined.endswith(".mp4")


def test_clip_args_no_audio_maps_none():
    cfg = build_config()
    plan = plan_for_dims(640, 360, cfg.reframe)
    args, _, _ = _clip_args(
        clip=_clip(),
        source="/src/v.mp4",
        plan=plan,
        cfg=cfg,
        gain_db=0.0,
        ass_path=None,
        out_path=Path("/out/c.mp4"),
        crf=19,
        preset="medium",
        has_audio=False,
        burn=False,
    )
    joined = " ".join(args)
    assert "-an" in joined and "0:a:0" not in joined and "-af" not in joined


# ---------------------------------------------------------------------------
# L5/L3 fixture: a real 640×360 16:9 video with an audio track
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def render_video(_media_dir):
    path = _media_dir / "render_16x9_audio.mp4"
    ffmpeg.run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "4",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(path),
        ]
    )
    return path


def _render_project(tmp_path: Path, video: Path, *, with_reframe: bool = True) -> Path:
    media = {
        "schema": "media-info",
        "source": str(video),
        "source_kind": "file",
        "container": "mp4",
        "stream_index": 0,
        "codec": "h264",
        "width": 640,
        "height": 360,
        "pixel_format": "yuv420p",
        "duration": 4.0,
        "start_time": 0.0,
        "time_base": "1/90000",
        "avg_frame_rate": "30/1",
        "frame_count": 120,
        "aspect_ratio": 1.7778,
        "display_aspect_ratio": "16:9",
        "rotation": 0.0,
        "analysis": {"start": 0.0, "end": 4.0},
    }
    analysis = {
        "schema": "analysis",
        "media": media,
        "audio": {
            "schema": "audio-info",
            "loudness": {"integrated_lufs": -24.0, "true_peak_db": -4.0},
        },
    }
    ranking = {
        "schema": "ranking",
        "selected": [
            _clip(id="c0001", rank=1, start=0.5, end=1.3, duration=0.8),
            _clip(id="c0002", rank=2, start=1.8, end=2.6, duration=0.8),
        ],
        "rejected": [],
        "decisions": [],
    }
    (tmp_path / "analysis.json").write_text(dump_str(analysis), encoding="utf-8")
    (tmp_path / "ranking.json").write_text(dump_str(ranking), encoding="utf-8")
    if with_reframe:
        write_json(
            tmp_path / "reframe.json",
            build_reframe_plan(MediaInfo(**media), build_config()),
        )
    return tmp_path / "ranking.json"


def _media_dims(path: Path) -> tuple[int, int]:
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return video["width"], video["height"]


def test_render_e2e_ffprobe(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    result = runner.invoke(app, ["render", str(ranking), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    for clip_id in ("c0001", "c0002"):
        out = tmp_path / "clips" / f"{clip_id}.mp4"
        assert out.is_file() and out.stat().st_size > 0
        assert _media_dims(out) == OUT
        data = probe(out)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        assert video["codec_name"] == "h264"
        audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
        assert audio["codec_name"] == "aac"
        assert abs(float(data["format"]["duration"]) - 0.8) <= 0.1
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert rdoc["schema"] == "render"
    assert check_contract(rdoc) == []
    assert rdoc["clips"][0]["gain_db"] == 2.5  # min(+8.0 LUFS, +2.5 peak headroom)
    assert rdoc["clips"][0]["status"] == "rendered"
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "ffmpeg" in man["tools"] and "ffprobe" in man["tools"]


def test_render_builds_missing_reframe(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video, with_reframe=False)
    assert not (tmp_path / "reframe.json").exists()
    result = runner.invoke(app, ["render", str(ranking), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "reframe.json").is_file()


def test_render_gamer_profile_composite(tmp_path, render_video):
    """`clipper render -p gaming --reframe` → gamer vstack plan + 1080×1920 clips."""
    ranking = _render_project(tmp_path, render_video)
    result = runner.invoke(
        app, ["render", str(ranking), "-p", "gaming", "--reframe", "--log-level", "error"]
    )
    assert result.exit_code == 0, result.output
    reframe = json.loads((tmp_path / "reframe.json").read_text(encoding="utf-8"))
    assert reframe["layout"] == "gamer" and reframe["strategy"] is None
    assert [z["role"] for z in reframe["zones"]] == ["gameplay", "facecam"]
    assert sum(z["height"] for z in reframe["zones"]) == reframe["output"]["height"]
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert all("vstack=inputs=2" in c["filters"] for c in rdoc["clips"])
    for clip_id in ("c0001", "c0002"):
        assert _media_dims(tmp_path / "clips" / f"{clip_id}.mp4") == OUT
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert man["config"]["reframe"]["mode"] == "gamer"


def test_render_skip_exists_and_force(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    cfg = tmp_path / "no_overwrite.yaml"
    cfg.write_text("render:\n  overwrite_output: false\n", encoding="utf-8")
    first = runner.invoke(app, ["render", str(ranking), "-c", str(cfg), "--log-level", "error"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["render", str(ranking), "-c", str(cfg), "--log-level", "error"])
    assert second.exit_code == 0, second.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert {c["status"] for c in rdoc["clips"]} == {"exists"}
    forced = runner.invoke(
        app, ["render", str(ranking), "-c", str(cfg), "--force", "--log-level", "error"]
    )
    assert forced.exit_code == 0, forced.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert {c["status"] for c in rdoc["clips"]} == {"rendered"}


def test_render_cli_crf_preset_override(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    result = runner.invoke(
        app, ["render", str(ranking), "--crf", "28", "--preset", "veryfast", "--log-level", "error"]
    )
    assert result.exit_code == 0, result.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert rdoc["video"]["crf"] == 28
    assert rdoc["video"]["preset"] == "veryfast"


def test_render_burn_subtitles(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    cap_dir = tmp_path / "captions"
    cap_dir.mkdir()
    (cap_dir / "c0001.ass").write_text(ASS_FIXTURE, encoding="utf-8")
    (cap_dir / "c0002.ass").write_text(ASS_FIXTURE, encoding="utf-8")
    if not ffmpeg.has_filter("subtitles"):
        pytest.skip("libass absent — degraded path covered by test_render_degraded_no_libass")
    result = runner.invoke(app, ["render", str(ranking), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert rdoc["burn"] is True
    assert all(c["burned"] for c in rdoc["clips"])
    assert all("subtitles=filename=" in c["filters"] for c in rdoc["clips"])
    assert _media_dims(tmp_path / "clips" / "c0001.mp4") == OUT


def test_render_no_burn_flag(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    cap_dir = tmp_path / "captions"
    cap_dir.mkdir()
    (cap_dir / "c0001.ass").write_text(ASS_FIXTURE, encoding="utf-8")
    result = runner.invoke(app, ["render", str(ranking), "--no-burn", "--log-level", "error"])
    assert result.exit_code == 0, result.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert rdoc["burn"] is False
    assert all(not (c["filters"] or "").count("subtitles") for c in rdoc["clips"])


def test_render_degraded_no_libass(tmp_path, render_video, monkeypatch):
    ranking = _render_project(tmp_path, render_video)
    cap_dir = tmp_path / "captions"
    cap_dir.mkdir()
    (cap_dir / "c0001.ass").write_text(ASS_FIXTURE, encoding="utf-8")
    (cap_dir / "c0002.ass").write_text(ASS_FIXTURE, encoding="utf-8")
    monkeypatch.setattr(ffmpeg, "has_filter", lambda name: False)
    result = runner.invoke(app, ["render", str(ranking), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert rdoc["burn"] is False and rdoc["degraded"] == ["burn_sidecar_only"]
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert man["degraded"] == ["burn_sidecar_only"]


def test_render_captions_on_no_transcript_degrades(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    result = runner.invoke(app, ["render", str(ranking), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    rdoc = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert rdoc["burn"] is False
    assert "captions_unavailable" in rdoc["degraded"]
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "captions_unavailable" in man["degraded"]


# ---------------------------------------------------------------------------
# L5: clipper render errors
# ---------------------------------------------------------------------------


def test_render_rejects_non_ranking(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "candidates"}), encoding="utf-8")
    result = runner.invoke(app, ["render", str(bad)])
    assert result.exit_code == 1
    assert "not a ranking document" in result.output


def test_render_missing_analysis(tmp_path):
    ranking = tmp_path / "ranking.json"
    ranking.write_text(dump_str({"schema": "ranking", "selected": [_clip()]}), encoding="utf-8")
    result = runner.invoke(app, ["render", str(ranking)])
    assert result.exit_code == 1
    assert "sibling analysis.json" in result.output


def test_render_missing_source(tmp_path):
    ranking = _render_project(tmp_path, Path("/definitely/not/here.mp4"))
    result = runner.invoke(app, ["render", str(ranking)])
    assert result.exit_code == 1
    assert "source video not found" in result.output


def test_render_bad_captions_mode(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    result = runner.invoke(app, ["render", str(ranking), "--captions", "sometimes"])
    assert result.exit_code == 1
    assert "invalid --captions" in result.output


def test_render_bad_crf(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    result = runner.invoke(app, ["render", str(ranking), "--crf", "99"])
    assert result.exit_code == 1
    assert "--crf must be in 0–51" in result.output


def test_render_accepts_project_dir(tmp_path, render_video):
    _render_project(tmp_path, render_video)
    result = runner.invoke(app, ["render", str(tmp_path), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "clips" / "c0001.mp4").is_file()


def test_render_output_flag_relocates_clips(tmp_path, render_video):
    ranking = _render_project(tmp_path, render_video)
    out = tmp_path / "out"
    result = runner.invoke(app, ["render", str(ranking), "-o", str(out), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (out / "clips" / "c0001.mp4").is_file()
    assert (out / "render.json").is_file() and (out / "manifest.json").is_file()
    assert _media_dims(out / "clips" / "c0001.mp4") == OUT
