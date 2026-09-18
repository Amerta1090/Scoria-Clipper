"""Sprint 10: report/preview/explain — pure builders, HTML renderer, CLI + L3 dims.

L0 pins the still arg surface, sampling geometry, timeline SVG and the HTML
renderer (score-table rows, base64 embedding vs relative links); L5 pins
`clipper explain` (embedded breakdown equality, text/json/yaml, error exits) and
`clipper report`/`preview` (assets, no analysis rerun, summary JSON, determinism);
L3 probes the generated stills with ffprobe to assert exact preview dimensions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.errors import PipelineError
from scoria.ingest.ffprobe import probe
from scoria.project import check_contract, dump_str
from scoria.rank import rank_candidates
from scoria.report import preview_project
from scoria.report.explain import explain_one, render_explain
from scoria.report.graph import contact_sheet_args, sample_times, thumbnail_args, timeline_svg
from scoria.report.html import render_report_html
from scoria.score import score_candidates
from scoria.segment import build_candidates

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS_SMALL = FIXTURES / "analysis_small.json"

PREVIEW = (320, 180)  # 640×360 16:9 scaled to preview_width 320, even height


def _clip(**overrides) -> dict:
    clip = {
        "id": "c0001",
        "rank": 1,
        "start": 0.5,
        "end": 1.3,
        "duration": 0.8,
        "score": 60.0,
        "gain": 60.0,
        "gain_note": "best",
        "overlap_seconds": 0.0,
        "overlap_penalty": 0.0,
        "jaccard_max": 0.0,
        "sim_penalty": 0.0,
        "gap": None,
        "gap_penalty": 0.0,
    }
    clip.update(overrides)
    return clip


def _breakdown(**overrides) -> dict:
    data = {
        "total": 64.0449,
        "subscore_sum": 64.0449,
        "penalty_total": 0.0,
        "renorm_factor": 1.0,
        "terms": [
            {
                "term": "audio_energy",
                "function": "energy.mean_clamp.smoothstep.v1",
                "inputs": {"mean": 0.4},
                "raw": 0.4,
                "normalized": 0.4,
                "weight": 0.2,
                "weighted": 8.0,
                "note": "loud and steady",
            }
        ],
        "penalties": [],
    }
    data.update(overrides)
    return data


def _report_project(tmp_path: Path, video: Path) -> Path:
    media = {
        "schema": "media-info",
        "source": str(video),
        "width": 640,
        "height": 360,
        "duration": 3.0,
        "aspect_ratio": 1.7778,
        "display_aspect_ratio": "16:9",
    }
    analysis = {"schema": "analysis", "media": media, "audio": {}}
    ranking = {
        "schema": "ranking",
        "version": 1,
        "rank_version": "greedy.marginal_gain.v1",
        "top": 2,
        "enabled": True,
        "stopped": False,
        "stop_reason": None,
        "min_margin": 20.0,
        "config": {},
        "note": "",
        "selected": [
            _clip(id="c0001", rank=1, start=0.5, end=1.3, duration=0.8),
            _clip(id="c0002", rank=2, start=1.5, end=2.3, duration=0.8, gain=50.0),
        ],
        "rejected": [],
        "decisions": [],
    }
    (tmp_path / "analysis.json").write_text(dump_str(analysis), encoding="utf-8")
    (tmp_path / "ranking.json").write_text(dump_str(ranking), encoding="utf-8")
    return tmp_path


def _explain_project(tmp_path: Path) -> Path:
    """A realistic project: analysis_small → segment → score → rank (no media)."""
    analysis = json.loads(ANALYSIS_SMALL.read_text(encoding="utf-8"))
    cfg = build_config()
    scored = score_candidates(build_candidates(analysis, cfg), cfg, analysis_data=analysis)
    ranking = rank_candidates(scored, cfg, top=3)
    (tmp_path / "candidates.json").write_text(dump_str(scored), encoding="utf-8")
    (tmp_path / "ranking.json").write_text(dump_str(ranking), encoding="utf-8")
    return tmp_path


def _image_dims(path: Path) -> tuple[int, int]:
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return video["width"], video["height"]


# ---------------------------------------------------------------------------
# L0: pure geometry + ffmpeg arg surface
# ---------------------------------------------------------------------------


def test_sample_times_midpoint_and_edges():
    assert sample_times(1.0, 2.0, 1) == [1.5]
    assert sample_times(1.0, 2.0, 3) == [1.0, 1.5, 2.0]
    assert sample_times(1.0, 2.0, 5) == [1.0, 1.25, 1.5, 1.75, 2.0]


def test_sample_times_rejects_zero_count():
    with pytest.raises(ValueError):
        sample_times(0.0, 1.0, 0)


def test_thumbnail_args_surface():
    args = thumbnail_args("/src/v.mp4", 1.2345, Path("/out/c0001.png"), 320)
    assert args == [
        "-ss",
        "1.2345",
        "-i",
        "/src/v.mp4",
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-2",
        "-y",
        "/out/c0001.png",
    ]


def test_contact_sheet_args_hstack():
    frames = [Path(f"/t/f{i}.png") for i in range(5)]
    args = contact_sheet_args(frames, Path("/t/sheet.png"))
    assert "-filter_complex" in args
    fc = args[args.index("-filter_complex") + 1]
    assert fc == "[0:v][1:v][2:v][3:v][4:v]hstack=inputs=5"
    assert args[-1] == "/t/sheet.png"


def test_contact_sheet_args_single_frame_passthrough():
    args = contact_sheet_args([Path("/t/f0.png")], Path("/t/sheet.png"))
    assert args == ["-i", "/t/f0.png", "-frames:v", "1", "-y", "/t/sheet.png"]


def test_contact_sheet_args_rejects_empty():
    with pytest.raises(ValueError):
        contact_sheet_args([], Path("/t/x.png"))


def test_timeline_svg_geometry_and_determinism():
    clips = [_clip(id="c0001", rank=1, start=2.0, end=3.0, duration=1.0)]
    svg = timeline_svg(10.0, clips, 1000, 48)
    assert 'width="1000"' in svg
    assert 'viewBox="0 0 1000 48"' in svg
    assert 'x="200.0"' in svg and 'width="100.0"' in svg
    assert svg == timeline_svg(10.0, clips, 1000, 48)


def test_timeline_svg_min_block_and_bad_duration():
    clips = [_clip(rank=2, start=0.0, end=0.05, duration=0.05)]
    assert 'width="2.0"' in timeline_svg(100.0, clips, 1000)
    with pytest.raises(ValueError):
        timeline_svg(0.0, clips, 1000)


# ---------------------------------------------------------------------------
# L0: explain join + renderers (embedded breakdown is passed through untouched)
# ---------------------------------------------------------------------------


def test_explain_one_matches_embedded_breakdown():
    breakdown = _breakdown()
    candidates = {
        "schema": "candidates",
        "candidates": [
            {"id": "c0001", "start": 1.0, "end": 2.0, "duration": 1.0, "score": breakdown}
        ],
    }
    ranking = {
        "schema": "ranking",
        "selected": [{"id": "c0001", "rank": 1, "gain": 64.0449, "gain_note": "best"}],
        "rejected": [],
        "decisions": [{"step": 1, "selected": "c0001"}],
    }
    data = explain_one(ranking, candidates, "c0001")
    assert data["breakdown"] is breakdown
    assert data["ranking"]["status"] == "selected"
    assert data["ranking"]["step"] == 1
    text = render_explain(data, "text")
    assert "64.0449" in text and "audio_energy" in text
    assert "energy.mean_clamp.smoothstep.v1" in text
    payload = json.loads(render_explain(data, "json"))
    assert payload["breakdown"] == breakdown
    assert yaml.safe_load(render_explain(data, "yaml"))["breakdown"] == breakdown


def test_explain_rejected_context():
    candidates = {
        "schema": "candidates",
        "candidates": [
            {"id": "c0002", "start": 1.0, "end": 2.0, "duration": 1.0, "score": _breakdown()}
        ],
    }
    ranking = {
        "schema": "ranking",
        "selected": [],
        "rejected": [
            {"id": "c0002", "score": 50.0, "best_gain": 10.0, "step": 1, "reason": "margin stop"}
        ],
        "decisions": [],
    }
    data = explain_one(ranking, candidates, "c0002")
    assert data["ranking"]["status"] == "rejected"
    assert "rejected" in render_explain(data, "text")


def test_explain_one_unknown_clip_raises():
    candidates = {"schema": "candidates", "candidates": []}
    with pytest.raises(PipelineError, match="not in candidates"):
        explain_one({"schema": "ranking"}, candidates, "c9999")


def test_explain_one_unscored_clip_raises():
    candidates = {
        "schema": "candidates",
        "candidates": [{"id": "c0001", "start": 0.0, "end": 1.0, "duration": 1.0}],
    }
    with pytest.raises(PipelineError, match="no embedded ScoreBreakdown"):
        explain_one({"schema": "ranking"}, candidates, "c0001")


def test_explain_one_rejects_non_candidates_doc():
    with pytest.raises(PipelineError, match="schema != 'candidates'"):
        explain_one({"schema": "ranking"}, {"schema": "analysis"}, "c0001")


# ---------------------------------------------------------------------------
# L0: HTML renderer (rows, embedding, config switches)
# ---------------------------------------------------------------------------


def _previews_doc(tmp_path: Path) -> dict:
    previews_dir = tmp_path / "previews"
    previews_dir.mkdir(exist_ok=True)
    (previews_dir / "c0001.png").write_bytes(b"png-thumb")
    (previews_dir / "c0001.sheet.png").write_bytes(b"png-sheet")
    (previews_dir / "timeline.svg").write_text("<svg><rect/></svg>\n", encoding="utf-8")
    return {
        "schema": "previews",
        "version": 1,
        "preview_version": "still.mid.v1",
        "source": "v.mp4",
        "media_duration": 3.0,
        "clips": [
            {
                "rank": 1,
                "id": "c0001",
                "start": 0.5,
                "end": 1.3,
                "duration": 0.8,
                "thumbnail": "previews/c0001.png",
                "contact_sheet": "previews/c0001.sheet.png",
                "strip_times": [0.5, 0.7, 0.9, 1.1, 1.3],
            }
        ],
        "timeline": {"file": "previews/timeline.svg"},
    }


def test_render_report_html_rows_and_embed(tmp_path):
    ranking = {"selected": [_clip(score=64.0449)]}
    html_text = render_report_html(
        previews=_previews_doc(tmp_path), ranking=ranking, cfg=build_config(), project_dir=tmp_path
    )
    assert html_text.count("<td>c0001</td>") == 1
    assert "64.0449" in html_text
    assert "data:image/png;base64," in html_text
    assert "<svg><rect/></svg>" in html_text  # timeline inlined, not linked


def test_render_report_html_links_and_no_score_table(tmp_path):
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "report:\n  embed_images: false\n  include_score_table: false\n", encoding="utf-8"
    )
    cfg = build_config(path=cfg_file)
    html_text = render_report_html(
        previews=_previews_doc(tmp_path),
        ranking={"selected": [_clip()]},
        cfg=cfg,
        project_dir=tmp_path,
    )
    assert 'src="previews/c0001.png"' in html_text
    assert "data:image/png;base64," not in html_text
    assert "<h2>Scores</h2>" not in html_text


# ---------------------------------------------------------------------------
# L5: `clipper explain`
# ---------------------------------------------------------------------------


def test_cli_explain_json_matches_embedded_breakdown(tmp_path):
    project = _explain_project(tmp_path)
    scored = json.loads((project / "candidates.json").read_text(encoding="utf-8"))
    ranking = json.loads((project / "ranking.json").read_text(encoding="utf-8"))
    clip_id = ranking["selected"][0]["id"]
    embedded = next(c for c in scored["candidates"] if c["id"] == clip_id)["score"]

    result = runner.invoke(app, ["explain", str(project), clip_id, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["breakdown"] == embedded
    assert payload["ranking"]["status"] == "selected"


def test_cli_explain_text_default(tmp_path):
    project = _explain_project(tmp_path)
    clip_id = json.loads((project / "ranking.json").read_text(encoding="utf-8"))["selected"][0][
        "id"
    ]
    result = runner.invoke(app, ["explain", str(project), clip_id])
    assert result.exit_code == 0, result.output
    assert clip_id in result.output
    assert "terms:" in result.output and "ranking: selected" in result.output


def test_cli_explain_yaml_format(tmp_path):
    project = _explain_project(tmp_path)
    clip_id = json.loads((project / "ranking.json").read_text(encoding="utf-8"))["selected"][0][
        "id"
    ]
    result = runner.invoke(app, ["explain", str(project), clip_id, "--format", "yaml"])
    assert result.exit_code == 0, result.output
    loaded = yaml.safe_load(result.output)
    assert loaded["clip"] == clip_id and "breakdown" in loaded


def test_cli_explain_unknown_clip_exits_one(tmp_path):
    project = _explain_project(tmp_path)
    result = runner.invoke(app, ["explain", str(project), "c9999"])
    assert result.exit_code == 1
    assert "not in candidates" in result.output


def test_cli_explain_bad_format_exits_two(tmp_path):
    project = _explain_project(tmp_path)
    result = runner.invoke(app, ["explain", str(project), "c0001", "--format", "xml"])
    assert result.exit_code == 2
    assert "invalid --format" in result.output


# ---------------------------------------------------------------------------
# L5/L3: `clipper report` / `clipper preview`
# ---------------------------------------------------------------------------


def test_cli_report_e2e_dims_and_html(tmp_path, landscape):
    project = _report_project(tmp_path, landscape)
    result = runner.invoke(app, ["report", str(project), "--log-level", "error"])
    assert result.exit_code == 0, result.output

    previews = project / "previews"
    assert (previews / "previews.json").is_file()
    assert (previews / "timeline.svg").is_file()
    assert (project / "report.html").is_file()
    for clip_id in ("c0001", "c0002"):
        thumb = previews / f"{clip_id}.png"
        sheet = previews / f"{clip_id}.sheet.png"
        assert thumb.is_file() and thumb.stat().st_size > 0
        assert sheet.is_file() and sheet.stat().st_size > 0
        assert _image_dims(thumb) == PREVIEW
        assert _image_dims(sheet) == (PREVIEW[0] * 5, PREVIEW[1])

    doc = json.loads((previews / "previews.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "previews" and doc["version"] == 1
    assert doc["preview_version"] == "still.mid.v1"
    assert doc["samples_per_clip"] == 5
    assert check_contract(doc) == []

    html_text = (project / "report.html").read_text(encoding="utf-8")
    assert html_text.count("<td>c0001</td>") == 1
    assert html_text.count("<td>c0002</td>") == 1
    assert "data:image/png;base64," in html_text


def test_cli_preview_assets_only(tmp_path, landscape):
    project = _report_project(tmp_path, landscape)
    result = runner.invoke(app, ["preview", str(project), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (project / "previews" / "previews.json").is_file()
    assert not (project / "report.html").exists()


def test_cli_preview_json_summary(tmp_path, landscape):
    project = _report_project(tmp_path, landscape)
    result = runner.invoke(app, ["preview", str(project), "--json", "--log-level", "error"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["clips"] == 2
    assert payload["preview_version"] == "still.mid.v1"


def test_cli_report_missing_ranking_exits_one(tmp_path, landscape):
    media = {"schema": "media-info", "source": str(landscape), "duration": 3.0}
    (tmp_path / "analysis.json").write_text(
        dump_str({"schema": "analysis", "media": media}), encoding="utf-8"
    )
    result = runner.invoke(app, ["report", str(tmp_path), "--log-level", "error"])
    assert result.exit_code == 1
    assert "ranking.json" in result.output


def test_report_assets_byte_stable(tmp_path, landscape):
    project = _report_project(tmp_path, landscape)
    assert runner.invoke(app, ["preview", str(project), "--log-level", "error"]).exit_code == 0
    first = {
        name: (project / "previews" / name).read_bytes()
        for name in ("previews.json", "c0001.png", "c0001.sheet.png", "timeline.svg")
    }
    assert runner.invoke(app, ["preview", str(project), "--log-level", "error"]).exit_code == 0
    for name, payload in first.items():
        assert (project / "previews" / name).read_bytes() == payload, name


# ---------------------------------------------------------------------------
# Input validation: report/preview never re-analyze, so bad artifacts fail loud
# ---------------------------------------------------------------------------


def _write_analysis(tmp_path: Path, media: dict, ranking: dict | None) -> Path:
    path = tmp_path / "analysis.json"
    path.write_text(dump_str({"schema": "analysis", "media": media}), encoding="utf-8")
    if ranking is not None:
        (tmp_path / "ranking.json").write_text(dump_str(ranking), encoding="utf-8")
    return path


def test_preview_rejects_non_analysis_doc(tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(PipelineError, match="schema != 'analysis'"):
        preview_project(path, cfg=build_config())


def test_preview_requires_media_section(tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text(dump_str({"schema": "analysis"}), encoding="utf-8")
    with pytest.raises(PipelineError, match="no media section"):
        preview_project(path, cfg=build_config())


def test_preview_requires_ranking(tmp_path, landscape):
    media = {"schema": "media-info", "source": str(landscape), "duration": 3.0}
    path = _write_analysis(tmp_path, media, None)
    with pytest.raises(PipelineError, match="sibling ranking.json"):
        preview_project(path, cfg=build_config())


def test_preview_rejects_non_ranking(tmp_path, landscape):
    media = {"schema": "media-info", "source": str(landscape), "duration": 3.0}
    path = _write_analysis(tmp_path, media, None)
    (tmp_path / "ranking.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PipelineError, match="schema != 'ranking'"):
        preview_project(path, cfg=build_config())


def test_preview_requires_selected_clips(tmp_path, landscape):
    media = {"schema": "media-info", "source": str(landscape), "duration": 3.0}
    path = _write_analysis(tmp_path, media, {"schema": "ranking", "selected": []})
    with pytest.raises(PipelineError, match="no selected clips"):
        preview_project(path, cfg=build_config())


def test_preview_missing_source_raises(tmp_path):
    media = {"schema": "media-info", "source": "/nonexistent/v.mp4", "duration": 3.0}
    path = _write_analysis(tmp_path, media, {"schema": "ranking", "selected": [_clip()]})
    with pytest.raises(PipelineError, match="source video not found"):
        preview_project(path, cfg=build_config())


def test_preview_non_positive_duration_raises(tmp_path, landscape):
    media = {"schema": "media-info", "source": str(landscape), "duration": 0.0}
    path = _write_analysis(tmp_path, media, {"schema": "ranking", "selected": [_clip()]})
    with pytest.raises(PipelineError, match="non-positive duration"):
        preview_project(path, cfg=build_config())


def test_preview_grab_failure_wraps_hint(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video", encoding="utf-8")
    media = {"schema": "media-info", "source": str(bad), "duration": 1.0}
    path = _write_analysis(
        tmp_path,
        media,
        {"schema": "ranking", "selected": [_clip(start=0.0, end=0.5, duration=0.5)]},
    )
    with pytest.raises(PipelineError, match="thumbnail grab failed"):
        preview_project(path, cfg=build_config())


# ---------------------------------------------------------------------------
# explain: penalty blocks + not-ranked / no-decision contexts
# ---------------------------------------------------------------------------


def test_explain_not_ranked_shows_penalties():
    breakdown = _breakdown(
        penalties=[
            {
                "rule": "leading_silence",
                "function": "penalty.edge_silence.v1",
                "inputs": {"seconds": 1.2},
                "value": -3.5,
                "note": "starts quiet",
            }
        ]
    )
    candidates = {
        "schema": "candidates",
        "candidates": [
            {"id": "c0003", "start": 0.0, "end": 1.0, "duration": 1.0, "score": breakdown}
        ],
    }
    ranking = {"schema": "ranking", "selected": [], "rejected": [], "decisions": []}
    data = explain_one(ranking, candidates, "c0003")
    assert data["ranking"]["status"] == "not_ranked"
    text = render_explain(data, "text")
    assert "penalties:" in text and "leading_silence" in text
    assert "not ranked" in text


def test_explain_selected_without_decision_step():
    candidates = {
        "schema": "candidates",
        "candidates": [
            {"id": "c0004", "start": 0.0, "end": 1.0, "duration": 1.0, "score": _breakdown()}
        ],
    }
    ranking = {
        "schema": "ranking",
        "selected": [{"id": "c0004", "rank": 1, "gain": 1.0, "gain_note": ""}],
        "rejected": [],
        "decisions": [],
    }
    data = explain_one(ranking, candidates, "c0004")
    assert data["ranking"]["step"] is None
    assert "selected rank #1" in render_explain(data, "text")
