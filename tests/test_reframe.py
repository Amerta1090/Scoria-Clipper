"""Sprint 8: reframe — pure crop/blur-pad geometry, CLI, L3 rendered dims.

L0 pins the closed-form geometry table (16:9 / 4:3 / 1:1 / 9:16 / 21:9 and a
taller-than-9:16 case) plus even-dim/chroma rounding; L5 pins `clipper reframe`
(reframe.json writing, post-MVP mode guard, bad-input errors); L3 renders a
testsrc2 through the plan's crop/scale and the blur-pad contain/bars geometry
and asserts exact 1080×1920 via ffprobe (the Sprint 9 DoD's "L3 ffprobe
check on rendered fixture" — rewired to the real `render.graph.build_video_chain`
when Sprint 9 landed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.config.schema import OutputConfig, ReframeConfig
from scoria.ingest.ffprobe import probe
from scoria.project import check_contract
from scoria.reframe import (
    REFRAME_PLAN_VERSION,
    REFRAME_SCHEMA,
    REFRAME_VERSION,
    ContentDims,
    CropRect,
    PadBars,
    compute_blur_pad,
    compute_crop,
    plan_for_dims,
    round_even,
    strategy_for,
)
from scoria.render.graph import build_video_chain
from scoria.util.ffmpeg import run_ffmpeg

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS_SMALL = FIXTURES / "analysis_small.json"

runner = CliRunner()

OUT = (1080, 1920)


def _cfg(**kw) -> ReframeConfig:
    return build_config().reframe.model_copy(update=kw)


# ---------------------------------------------------------------------------
# L0: rounding + strategy selection
# ---------------------------------------------------------------------------


def test_round_even():
    assert round_even(607.5) == 608  # half ties to even
    assert round_even(202.5) == 202
    assert round_even(562.5) == 562
    assert round_even(455.625) == 456
    assert round_even(360.0) == 360


def test_strategy_boundaries():
    assert strategy_for(1080, 1920, 1.78) == "scale"  # exactly 9:16
    assert strategy_for(1920, 1080, 1.78) == "crop"  # 16:9
    assert strategy_for(640, 480, 1.78) == "crop"  # 4:3
    assert strategy_for(1780, 1000, 1.78) == "crop"  # exactly the threshold
    assert strategy_for(2000, 1000, 1.78) == "blur_pad"  # 2:1 very-wide
    assert strategy_for(2560, 1080, 1.78) == "blur_pad"  # 21:9
    assert strategy_for(720, 1440, 1.78) == "blur_pad"  # taller than 9:16


# ---------------------------------------------------------------------------
# L0: geometry table (SPRINT_PLANNING §S8 acceptance: all ARs → 1080×1920)
# ---------------------------------------------------------------------------


def test_crop_geometry_table():
    cases = {
        (1920, 1080): CropRect(x=656, y=0, width=608, height=1080),  # 16:9
        (640, 480): CropRect(x=184, y=0, width=270, height=480),  # 4:3
        (1000, 1000): CropRect(x=220, y=0, width=562, height=1000),  # 1:1
    }
    for (w, h), crop in cases.items():
        plan = plan_for_dims(w, h, _cfg())
        assert plan.strategy == "crop"
        assert plan.crop == crop
        assert plan.content is None and plan.pad is None
        assert plan.output.width == OUT[0] and plan.output.height == OUT[1]


def test_scale_and_blur_pad_table():
    for w, h in [(1080, 1920), (2560, 1080), (720, 1440)]:
        plan = plan_for_dims(w, h, _cfg())
        assert plan.strategy == ("scale" if (w, h) == (1080, 1920) else "blur_pad")
        assert plan.crop is None
        if plan.strategy == "scale":
            assert plan.content is None and plan.pad is None
        else:
            assert plan.content is not None and plan.pad is not None


def test_blur_pad_21x9_geometry():
    content, pad = compute_blur_pad(2560, 1080, *OUT)
    assert content == ContentDims(width=1080, height=456)
    assert pad == PadBars(top=732, bottom=732, left=0, right=0)


def test_blur_pad_tall_geometry():
    content, pad = compute_blur_pad(720, 1440, *OUT)
    assert content == ContentDims(width=960, height=1920)
    assert pad == PadBars(top=0, bottom=0, left=60, right=60)


def test_blur_pad_custom_output():
    reframe = _cfg(output=OutputConfig(width=540, height=960))
    content, pad = compute_blur_pad(2560, 1080, 540, 960)
    assert content == ContentDims(width=540, height=228)
    assert pad == PadBars(top=366, bottom=366, left=0, right=0)
    plan = plan_for_dims(2560, 1080, reframe)
    assert plan.output.width == 540 and plan.output.height == 960


def test_odd_source_dims_round_even_and_in_bounds():
    plan = plan_for_dims(641, 361, _cfg())
    assert plan.strategy == "crop"
    crop = plan.crop
    assert crop.width % 2 == 0
    assert crop.x % 2 == 0 and crop.y == 0
    assert crop.x + crop.width <= 641


def test_crop_keeps_9x16_ratio_within_rounding():
    for w, h in [(1920, 1080), (640, 480), (1000, 1000), (641, 361)]:
        plan = plan_for_dims(w, h, _cfg())
        if plan.strategy != "crop":
            continue
        assert abs(plan.crop.width / plan.crop.height - 9 / 16) <= 2 / plan.crop.height


def test_plan_contract_fields():
    plan = plan_for_dims(1920, 1080, _cfg())
    assert plan.document_schema == REFRAME_SCHEMA
    assert plan.version == REFRAME_VERSION
    assert plan.reframe_version == REFRAME_PLAN_VERSION
    assert plan.mode == "center"
    assert abs(plan.source.aspect_ratio - 16 / 9) < 1e-3


def test_plan_deterministic():
    assert plan_for_dims(1920, 1080, _cfg()) == plan_for_dims(1920, 1080, _cfg())


def test_compute_crop_scale_only_input_never_used():
    # compute_crop is only called on the crop branch (AR ≥ 9:16); a 9:16
    # source must clamp in-bounds rather than produce an oversized window.
    crop = compute_crop(1080, 1920)
    assert crop.width <= 1080
    assert crop.x + crop.width <= 1080


def test_compute_crop_width_clamp_for_narrow_source():
    # Out-of-contract input (< 9:16 wide) that only the defensive clamp can
    # see: the crop width must be pulled back to an even in-bounds value.
    crop = compute_crop(179, 320)  # 179 < 320×9/16 = 180
    assert crop.width == 178
    assert crop.width % 2 == 0
    assert crop.x + crop.width <= 179


# ---------------------------------------------------------------------------
# L5: clipper reframe
# ---------------------------------------------------------------------------


def _project_with_analysis(tmp_path: Path, name: str = "proj") -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / "analysis.json").write_text(ANALYSIS_SMALL.read_text(encoding="utf-8"))
    return project


def test_reframe_cli_writes_plan(tmp_path):
    project = _project_with_analysis(tmp_path)
    result = runner.invoke(app, ["reframe", str(project)])
    assert result.exit_code == 0, result.output
    plan = json.loads((project / "reframe.json").read_text(encoding="utf-8"))
    assert check_contract(plan) == []
    assert plan["schema"] == REFRAME_SCHEMA
    assert plan["version"] == REFRAME_VERSION
    assert plan["reframe_version"] == REFRAME_PLAN_VERSION
    assert plan["strategy"] == "crop"  # 320×180 fixture is 16:9-ish
    assert plan["source"] == {"width": 320, "height": 180, "aspect_ratio": 1.7778}
    assert plan["output"] == {"width": 1080, "height": 1920}


def test_reframe_cli_json_summary(tmp_path):
    project = _project_with_analysis(tmp_path, "proj2")
    result = runner.invoke(app, ["reframe", str(project), "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["strategy"] == "crop"
    assert summary["reframe_version"] == REFRAME_PLAN_VERSION
    assert summary["target"] == {"width": 1080, "height": 1920}


def test_reframe_cli_rejects_post_mvp_mode(tmp_path):
    project = _project_with_analysis(tmp_path, "proj3")
    cfg = tmp_path / "faces.yaml"
    cfg.write_text("reframe:\n  mode: faces\n", encoding="utf-8")
    result = runner.invoke(app, ["reframe", str(project), "-c", str(cfg)])
    assert result.exit_code == 1
    assert "post-MVP" in result.output
    assert not (project / "reframe.json").exists()


def test_reframe_cli_bad_document(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "candidates"}), encoding="utf-8")
    result = runner.invoke(app, ["reframe", str(bad)])
    assert result.exit_code == 1
    assert "not an analysis document" in result.output


def test_reframe_cli_missing_media(tmp_path):
    doc = tmp_path / "no_media.json"
    doc.write_text(json.dumps({"schema": "analysis"}), encoding="utf-8")
    result = runner.invoke(app, ["reframe", str(doc)])
    assert result.exit_code == 1
    assert "no media section" in result.output


# ---------------------------------------------------------------------------
# L3: rendered fixture dims via ffprobe (Sprint 8 DoD)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ultra_wide(_media_dir):
    path = _media_dir / "ultrawide_21x9.mp4"
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x540:rate=10",
            "-t",
            "2",
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


def _video_dimensions(path: Path) -> tuple[int, int]:
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return video["width"], video["height"]


def test_l3_crop_render_dims(tmp_path, landscape):
    """16:9 640×360 → plan crop/scale → exact 1080×1920 (real graph builder)."""
    plan = plan_for_dims(640, 360, _cfg())
    assert plan.strategy == "crop"
    assert plan.crop == CropRect(x=220, y=0, width=202, height=360)
    target = tmp_path / "crop_16x9.mp4"
    fc, vf, label = build_video_chain(plan)
    assert fc is None and label is None and vf is not None
    run_ffmpeg(
        [
            "-y",
            "-i",
            str(landscape),
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-an",
            str(target),
        ]
    )
    assert _video_dimensions(target) == OUT


def test_l3_blur_pad_render_dims(tmp_path, ultra_wide):
    """21:9 1280×540 → contained overlay + blurred bars → exact 1080×1920."""
    plan = plan_for_dims(1280, 540, _cfg())
    assert plan.strategy == "blur_pad"
    assert plan.content == ContentDims(width=1080, height=456)
    assert plan.pad == PadBars(top=732, bottom=732, left=0, right=0)
    target = tmp_path / "blur_21x9.mp4"
    fc, vf, label = build_video_chain(plan)
    assert fc is not None and vf is None and label == "[vout]"
    run_ffmpeg(
        [
            "-y",
            "-i",
            str(ultra_wide),
            "-filter_complex",
            fc,
            "-map",
            label,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            str(target),
        ]
    )
    assert _video_dimensions(target) == OUT
