"""Sprint 4: segmentation — boundary union, window generator, golden candidates.

L0 tests exercise the pure builders with synthetic lists; the golden fixture
(`analysis_small.json`, 9 sentences + 1 scene, media 120 s) pins the exact
14-window output computed by hand (see module-level `GOLDEN_WINDOWS`); L5 covers
the `clipper segment` CLI contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.project import check_contract, dump_str
from scoria.segment import (
    BOUNDARY_DEDUPE_S,
    CANDIDATES_SCHEMA,
    build_boundaries,
    build_candidates,
    generate_candidates,
)
from scoria.segment.boundaries import BOUNDARY_SOURCE_ORDER

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS_SMALL = FIXTURES / "analysis_small.json"

runner = CliRunner()

KW = dict(
    media_start=0.0,
    media_end=120.0,
    min_duration=20.0,
    pref_min=35.0,
    pref_max=45.0,
    max_duration=60.0,
    max_candidates_per_start=2,
    hard_cut_margin=0.25,
)

# Hand-computed golden windows for the fixture's boundary set (0,4,12,18,30,40,48,
# 50,70,80,120): (A) nearest preferred then (B) max extension, deduped across starts.
GOLDEN_WINDOWS = [
    (0.0, 40.0),
    (0.0, 50.0),
    (4.0, 40.0),
    (4.0, 50.0),
    (12.0, 50.0),
    (12.0, 70.0),
    (18.0, 70.0),
    (30.0, 70.0),
    (30.0, 80.0),
    (40.0, 80.0),
    (48.0, 80.0),
    (50.0, 80.0),
    (70.0, 120.0),
    (80.0, 120.0),
]


def _cfg(**overrides):
    data: dict = {}
    data.update(overrides)
    return build_config(overrides=data)


def _fixture_analysis():
    return json.loads(ANALYSIS_SMALL.read_text(encoding="utf-8"))


def _windows(boundaries):
    return [(w.start, w.end) for w in generate_candidates(boundaries, **KW)]


def _fixture_boundaries():
    sentences = [
        (0, 4),
        (4, 12),
        (12, 18),
        (18, 30),
        (30, 40),
        (40, 48),
        (48, 70),
        (70, 80),
        (80, 120),
    ]
    return build_boundaries(sentences=sentences, scenes=[(50, 50)])


# ---------------------------------------------------------------------------
# L0: boundary building
# ---------------------------------------------------------------------------


def test_boundary_union_and_source_labels():
    boundaries = build_boundaries(
        silence=[(0.0, 0.5), (2.0, 4.0)],
        sentences=[(0.5, 2.0)],
        scenes=[(1.5, 1.5)],
    )
    assert [(b.time, b.sources) for b in boundaries] == [
        (0.0, ["silence_start"]),
        (0.5, ["sentence_start", "silence_end"]),
        (1.5, ["scene"]),
        (2.0, ["sentence_end", "silence_start"]),
        (4.0, ["silence_end"]),
    ]


def test_boundary_within_dedupe_window_merges():
    boundaries = build_boundaries(
        silence=[(0.49, 0.51)], scenes=[(0.50, 0.50)], dedupe_s=BOUNDARY_DEDUPE_S
    )
    assert len(boundaries) == 1
    assert boundaries[0].time == 0.49
    assert boundaries[0].sources == ["silence_start", "silence_end", "scene"]


def test_boundary_sources_follow_canonical_order():
    merged = build_boundaries(
        sentences=[(10.0, 10.02)], silence=[(10.0, 10.02)], scenes=[(10.01, 10.01)]
    )
    assert merged[0].sources == list(BOUNDARY_SOURCE_ORDER)


def test_boundary_deterministic_order():
    full = [
        (0, 4),
        (4, 12),
        (12, 18),
        (18, 30),
        (30, 40),
        (40, 48),
        (48, 70),
        (70, 80),
        (80, 120),
    ]
    first = build_boundaries(sentences=full, scenes=[(50, 50)])
    second = build_boundaries(sentences=list(reversed(full)), scenes=[(50, 50), (50, 50)])
    assert [(b.time, b.sources) for b in first] == [(b.time, b.sources) for b in second]


# ---------------------------------------------------------------------------
# L0: window generator
# ---------------------------------------------------------------------------


def test_generator_golden_windows():
    assert _windows(_fixture_boundaries()) == GOLDEN_WINDOWS


def test_generator_hard_cut_for_long_sentence():
    boundaries = build_boundaries(sentences=[(0, 90)])
    windows = generate_candidates(boundaries, **KW)
    assert [(w.start, w.end, w.hard_cut) for w in windows] == [
        (0.0, 60.0, True),
        (90.0, 120.0, True),
    ]
    assert all(not w.end_sources for w in windows)


def test_generator_margin_grace_lands_on_real_boundary():
    boundaries = build_boundaries(sentences=[(0, 120)], scenes=[(60.2, 60.2)])
    windows = generate_candidates(boundaries, **KW)
    assert [(w.start, w.end, w.hard_cut) for w in windows] == [
        (0.0, 60.2, False),
        (60.2, 120.0, False),
    ]


def test_generator_margin_ignored_beyond_grace():
    boundaries = build_boundaries(sentences=[(0, 120)], scenes=[(61.0, 61.0)])
    windows = generate_candidates(boundaries, **KW)
    assert (windows[0].start, windows[0].end, windows[0].hard_cut) == (0.0, 60.0, True)


def test_generator_skips_starts_that_cannot_reach_min():
    boundaries = build_boundaries(sentences=[(110, 130)])
    windows = generate_candidates(boundaries, **KW)
    assert windows == []


def test_generator_respects_max_candidates_per_start():
    one = generate_candidates(_fixture_boundaries(), **{**KW, "max_candidates_per_start": 1})
    assert [w.end for w in one] == [40.0, 40.0, 50.0, 70.0, 70.0, 80.0, 80.0, 80.0, 120.0, 120.0]


# ---------------------------------------------------------------------------
# L1: build_candidates on the golden fixture
# ---------------------------------------------------------------------------


def test_golden_candidates_set():
    data = build_candidates(_fixture_analysis(), _cfg())
    assert data["schema"] == CANDIDATES_SCHEMA
    assert [(c["start"], c["end"]) for c in data["candidates"]] == GOLDEN_WINDOWS


def test_golden_candidate_ids_and_flags():
    data = build_candidates(_fixture_analysis(), _cfg())
    assert [c["id"] for c in data["candidates"]] == [
        f"c{i:04d}" for i in range(1, len(data["candidates"]) + 1)
    ]
    by = {(c["start"], c["end"]): c for c in data["candidates"]}
    assert by[(0.0, 40.0)]["aligned_to"] == ["sentence_start", "sentence_end"]
    assert by[(0.0, 40.0)]["hard_cut"] is False
    assert by[(0.0, 40.0)]["mid_sentence_start"] is False
    assert by[(0.0, 40.0)]["mid_sentence_end"] is False
    assert by[(0.0, 50.0)]["aligned_to"] == ["sentence_start", "scene"]
    assert by[(0.0, 50.0)]["mid_sentence_end"] is True  # scene, not a sentence end
    assert by[(50.0, 80.0)]["mid_sentence_start"] is True
    assert {c["duration"] for c in data["candidates"]} == {
        30.0,
        32.0,
        36.0,
        38.0,
        40.0,
        46.0,
        50.0,
        52.0,
        58.0,
    }


def test_golden_candidate_slices():
    data = build_candidates(_fixture_analysis(), _cfg())
    first = data["candidates"][0]  # (0, 40)
    assert first["slices"]["audio"] == [0, 800]
    assert first["slices"]["sentences"] == [0, 1, 2, 3, 4]
    assert first["slices"]["words"] == list(range(10))
    assert first["slices"]["scenes"] == []
    scene_cut = next(c for c in data["candidates"] if c["end"] == 50.0)
    assert scene_cut["slices"]["scenes"] == [0]


def test_golden_boundaries_and_window():
    data = build_candidates(_fixture_analysis(), _cfg())
    assert data["window_start"] == 0.0
    assert data["window_end"] == 120.0
    assert data["media_duration"] == 120.0
    assert [(b["time"], b["sources"]) for b in data["boundaries"]] == [
        (0.0, ["sentence_start"]),
        (4.0, ["sentence_start", "sentence_end"]),
        (12.0, ["sentence_start", "sentence_end"]),
        (18.0, ["sentence_start", "sentence_end"]),
        (30.0, ["sentence_start", "sentence_end"]),
        (40.0, ["sentence_start", "sentence_end"]),
        (48.0, ["sentence_start", "sentence_end"]),
        (50.0, ["scene"]),
        (70.0, ["sentence_start", "sentence_end"]),
        (80.0, ["sentence_start", "sentence_end"]),
        (120.0, ["sentence_end"]),
    ]
    assert data["config"]["pref_min"] == 35.0
    assert data["config"]["scene_detection_threshold"] == 0.35


def test_golden_serializes_contract_clean():
    data = json.loads(dump_str(build_candidates(_fixture_analysis(), _cfg())))
    assert check_contract(data) == []


def test_golden_deterministic():
    data = build_candidates(_fixture_analysis(), _cfg())
    assert build_candidates(_fixture_analysis(), _cfg()) == data


# ---------------------------------------------------------------------------
# L1: degraded inputs
# ---------------------------------------------------------------------------


def test_build_candidates_without_transcript_uses_silence_scenes(tmp_path):
    analysis = _fixture_analysis()
    analysis["transcript"] = None
    analysis["visual"] = None
    analysis["audio"]["silence"] = [
        {"start": 0.0, "end": 1.0, "duration": 1.0},
        {"start": 55.0, "end": 56.0, "duration": 1.0},
    ]
    data = build_candidates(analysis, _cfg())
    assert data["candidates"] != []
    start_times = {b["time"] for b in data["boundaries"]}
    assert start_times == {0.0, 1.0, 55.0, 56.0}


def test_build_candidates_hard_cut_in_memory(tmp_path):
    analysis = _fixture_analysis()
    analysis["transcript"]["sentences"] = [
        {
            "text": "Satu kalimat sangat panjang sekali.",
            "start": 0.0,
            "end": 90.0,
            "words": [{"text": "Satu", "start": 0.0, "end": 90.0}],
        }
    ]
    analysis["transcript"]["sentence_count"] = 1
    analysis["visual"]["scenes"] = []
    analysis["visual"]["scene_count"] = 0
    analysis["audio"]["silence"] = []
    data = build_candidates(analysis, _cfg())
    assert [
        (c["start"], c["end"], c["hard_cut"], c["mid_sentence_end"]) for c in data["candidates"]
    ] == [
        (0.0, 60.0, True, True),
        (90.0, 120.0, True, True),
    ]


# ---------------------------------------------------------------------------
# L5: `clipper segment` CLI
# ---------------------------------------------------------------------------


def test_cli_segment_from_file(tmp_path):
    import shutil

    analysis = tmp_path / "analysis.json"
    shutil.copy(ANALYSIS_SMALL, analysis)
    out = tmp_path / "candidates.json"
    result = runner.invoke(app, ["segment", str(analysis), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == CANDIDATES_SCHEMA
    assert len(data["candidates"]) == len(GOLDEN_WINDOWS)
    assert check_contract(data) == []


def test_cli_segment_from_project_dir(tmp_path):
    out_dir = tmp_path / "proj"
    out_dir.mkdir()
    import shutil

    shutil.copy(ANALYSIS_SMALL, out_dir / "analysis.json")
    result = runner.invoke(app, ["segment", str(out_dir), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (out_dir / "candidates.json").exists()


def test_cli_segment_json_summary(tmp_path):
    import shutil

    analysis = tmp_path / "analysis.json"
    shutil.copy(ANALYSIS_SMALL, analysis)
    result = runner.invoke(app, ["segment", str(analysis), "--log-level", "error", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.strip().splitlines()[-1])
    assert summary["candidates"] == len(GOLDEN_WINDOWS)
    assert summary["boundaries"] == 11


def test_cli_segment_rejects_non_analysis_doc(tmp_path):
    bogus = tmp_path / "analysis.json"
    bogus.write_text('{"schema": "candidates"}', encoding="utf-8")
    result = runner.invoke(app, ["segment", str(bogus), "--log-level", "error"])
    assert result.exit_code == 1
    assert "analysis" in result.output

    missing = tmp_path / "nope.json"
    result = runner.invoke(app, ["segment", str(missing), "--log-level", "error"])
    assert result.exit_code == 1
    assert "not found" in result.output
