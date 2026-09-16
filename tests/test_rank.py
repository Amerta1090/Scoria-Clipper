"""Sprint 6: ranking + diversity — greedy marginal gain, penalties, AC, L5 CLI.

L0 tests pin the pure selection math (overlap/sim/gap penalties, hard spacing,
tie-break, margin stop); the AC test pins the sprint's acceptance criterion
(never 3 from the same minute when a spaced alternative exists); the determinism
test pins byte-identical re-ranking; L5 pins `clipper rank`. The fixture labels
test reports (not gates) precision/recall against human-labeled goods — the
numbering is deterministic, the threshold is informational (SCORING_ENGINE §8).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.project import check_contract, dump_str, normalize
from scoria.rank import RANK_VERSION, RANKING_SCHEMA, RANKING_VERSION, rank_candidates

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS_SMALL = FIXTURES / "analysis_small.json"
LABELS = FIXTURES / "ranking_labels.json"

runner = CliRunner()

DURATION = 400.0


def _candidate(
    cid: str,
    start: float,
    end: float,
    score: float,
    tokens: list[str] | None = None,
) -> dict:
    return {
        "id": cid,
        "start": start,
        "end": end,
        "duration": end - start,
        "aligned_to": ["sentence_start", "sentence_end"],
        "mid_sentence_start": False,
        "mid_sentence_end": False,
        "hard_cut": False,
        "slices": {"audio": [], "sentences": [], "words": [], "scenes": []},
        "score": {
            "total": score,
            "subscore_sum": score / 100.0,
            "penalty_total": 0.0,
            "renorm_factor": 1.0,
            "terms": [
                {
                    "term": "keyword_density",
                    "function": "keywords.hits_min.smoothstep.v1",
                    "inputs": {"window_words": list(tokens or [])},
                    "raw": 0.0,
                    "normalized": 0.0,
                    "weight": 0.06,
                    "weighted": 0.0,
                    "note": "",
                }
            ],
            "penalties": [],
        },
    }


def _enriched(candidates: list[dict]) -> dict:
    return {
        "schema": "candidates",
        "version": 2,
        "media_duration": DURATION,
        "window_start": 0.0,
        "window_end": DURATION,
        "config": {
            "min_duration": 20.0,
            "pref_min": 35.0,
            "pref_max": 45.0,
            "max_duration": 60.0,
            "max_candidates_per_start": 2,
            "hard_cut_margin": 0.25,
            "scene_detection_threshold": 0.35,
        },
        "boundaries": [],
        "candidates": candidates,
    }


def _rank(candidates: list[dict], top: int = 3, **ranking_overrides) -> dict:
    cfg = build_config(overrides={"scoring": {"ranking": ranking_overrides}})
    return rank_candidates(_enriched(candidates), cfg, top=top)


def _ids(ranking: dict) -> list[str]:
    return [s["id"] for s in ranking["selected"]]


# ---------------------------------------------------------------------------
# L0: core mechanics via synthetic candidates
# ---------------------------------------------------------------------------


def test_overlapping_clone_is_rejected():
    ranking = _rank(
        [
            _candidate("a", 0.0, 30.0, 70.0),
            _candidate("b", 0.0, 30.0, 70.0),  # full overlap: loses its whole score
        ]
    )
    assert _ids(ranking) == ["a"]
    assert ranking["stopped"] is True
    assert ranking["stop_reason"] == "margin"
    b = next(r for r in ranking["rejected"] if r["id"] == "b")
    assert "below min_margin" in b["reason"]
    step2 = next(m for m in ranking["decisions"][1]["candidates"] if m["id"] == "b")
    assert step2["overlap_penalty"] == 100.0
    assert step2["note"] == "dominant penalty overlap (100.00)"


def test_keyword_identical_loses_to_spaced_alternative():
    # b has the identical keyword set as a → heavy sim_pen; the spaced c wins.
    ranking = _rank(
        [
            _candidate("a", 0.0, 40.0, 60.0, tokens=["kunci", "tips", "cara"]),
            _candidate("b", 100.0, 140.0, 60.0, tokens=["kunci", "tips", "cara"]),
            _candidate("c", 300.0, 340.0, 58.0, tokens=["x", "y", "z"]),
        ]
    )
    assert _ids(ranking)[:2] == ["a", "c"]
    assert _ids(ranking)[0] == "a"
    b_record = next(m for m in ranking["decisions"][1]["candidates"] if m["id"] == "b")
    assert b_record["jaccard_max"] == pytest.approx(1.0)
    assert b_record["sim_penalty"] == pytest.approx(25.0)
    assert ranking["decisions"][1]["selected"] == "c"


def test_margin_stop_does_not_fill_quota():
    # Three clones only — best marginal gain collapses below min_margin.
    ranking = _rank(
        [
            _candidate("a", 0.0, 30.0, 70.0),
            _candidate("b", 0.0, 30.0, 70.0),
            _candidate("c", 0.0, 30.0, 70.0),
        ],
        top=3,
    )
    assert _ids(ranking) == ["a"]
    assert ranking["stopped"] and ranking["stop_reason"] == "margin"
    assert len(ranking["rejected"]) == 2
    assert all("below min_margin" in r["reason"] for r in ranking["rejected"])


def test_overlap_dominant_gain_note_when_still_selected():
    # Partial overlap (62.5 pen) with a high score keeps G above margin → the
    # 2nd selection documents overlap as the dominant penalty.
    ranking = _rank(
        [
            _candidate("hi", 0.0, 40.0, 100.0),
            _candidate("ov", 15.0, 55.0, 100.0),  # overlap 25/40 = 0.625 → ov_pen 62.5
        ]
    )
    assert [s["id"] for s in ranking["selected"]] == ["hi", "ov"]
    assert "dominant penalty overlap" in ranking["selected"][1]["gain_note"]


def test_hard_start_gap_exclusion_recorded_and_rejected():
    ranking = _rank(
        [
            _candidate("a", 0.0, 40.0, 60.0),
            _candidate("b", 2.0, 42.0, 60.0),  # always excluded by hard gap
            _candidate("c", 200.0, 240.0, 55.0),
        ],
        hard_min_start_gap=5.0,
    )
    assert _ids(ranking) == ["a", "c"]
    b_record = ranking["decisions"][1]["candidates"][0]
    assert b_record["id"] == "b" and b_record["excluded"] == "hard_start_gap"
    assert {r["id"] for r in ranking["rejected"]} == {"b"}


def test_gap_penalty_prefers_spaced_clips():
    # c is more spaced from a than b (b is adjacent) → lower gap_pen.
    ranking = _rank(
        [
            _candidate("a", 0.0, 40.0, 60.0),
            _candidate("b", 40.0, 80.0, 60.0),  # adjacent: gap 0 → full gap_pen
            _candidate("c", 160.0, 200.0, 60.0),  # gap 80 ≥ preferred (2×40)
        ],
        top=2,
    )
    assert _ids(ranking) == ["a", "c"]
    b_record = next(m for m in ranking["decisions"][1]["candidates"] if m["id"] == "b")
    assert b_record["gap_penalty"] == pytest.approx(15.0)
    c_record = next(m for m in ranking["decisions"][1]["candidates"] if m["id"] == "c")
    assert c_record["gap_penalty"] == pytest.approx(0.0)


def test_tie_break_by_start_then_id():
    # Two candidates, same score, identical window → earliest start, then stable id.
    ranking = _rank(
        [
            _candidate("c004", 0.0, 40.0, 50.0),
            _candidate("c001", 0.0, 40.0, 50.0),
        ]
    )
    assert ranking["selected"][0]["id"] == "c001"
    # Same score, distinct starts → earliest start wins.
    ranking2 = _rank(
        [
            _candidate("late", 200.0, 240.0, 50.0),
            _candidate("early", 0.0, 40.0, 50.0),
        ]
    )
    assert ranking2["selected"][0]["id"] == "early"


def test_hard_min_start_gap_excludes_candidates():
    ranking = _rank(
        [
            _candidate("a", 0.0, 40.0, 60.0),
            _candidate("b", 2.0, 42.0, 60.0),  # start within 5s of a
            _candidate("c", 200.0, 240.0, 55.0),
        ],
        hard_min_start_gap=5.0,
    )
    assert _ids(ranking) == ["a", "c"]
    b_record = next(m for m in ranking["decisions"][1]["candidates"] if m["id"] == "b")
    assert b_record["excluded"] == "hard_start_gap"
    assert b_record["gain"] is None


def test_ranking_disabled_returns_empty_doc():
    ranking = _rank([_candidate("a", 0.0, 30.0, 70.0)], enabled=False)
    assert ranking["enabled"] is False
    assert ranking["selected"] == []
    assert ranking["stopped"] is False
    assert "disabled" in ranking["note"]


def test_top_zero_selects_nothing():
    ranking = _rank([_candidate("a", 0.0, 30.0, 70.0)], top=0)
    assert ranking["selected"] == []
    assert ranking["stop_reason"] is None


def test_rank_version_and_schema_stamped():
    ranking = _rank([_candidate("a", 0.0, 40.0, 60.0)])
    assert ranking["schema"] == RANKING_SCHEMA
    assert ranking["version"] == RANKING_VERSION
    assert ranking["rank_version"] == RANK_VERSION
    assert check_contract(normalize(dump_str(ranking) and json.loads(dump_str(ranking)))) == []


def test_missing_scorebreakdown_raises():
    doc = _enriched([_candidate("b", 0.0, 30.0, 70.0)])
    del doc["candidates"][0]["score"]
    cfg = build_config()
    with pytest.raises(Exception, match="score"):
        rank_candidates(doc, cfg, top=3)


def test_determinism_byte_identical():
    candidates = [
        _candidate("c0001", 0.0, 40.0, 64.0),
        _candidate("c0002", 0.0, 50.0, 32.8),
        _candidate("c0003", 4.0, 40.0, 64.7),
        _candidate("c0006", 12.0, 70.0, 75.3),
        _candidate("c0007", 18.0, 70.0, 75.3),
        _candidate("c0008", 30.0, 70.0, 75.3),
        _candidate("c0013", 70.0, 120.0, 64.0),
        _candidate("c0014", 80.0, 120.0, 64.0),
    ]
    first = rank_candidates(_enriched(candidates), build_config(), top=3)
    second = rank_candidates(_enriched(candidates), build_config(), top=3)
    assert dump_str(first) == dump_str(second)


# ---------------------------------------------------------------------------
# Sprint 6 acceptance criterion
# ---------------------------------------------------------------------------


def test_never_picks_three_from_the_same_minute():
    # 6 candidates: 3 overlap one minute, 3 are genuinely spaced. The greedy
    # must pick at most a single clip from the crowded minute.
    ranking = _rank(
        [
            _candidate("oa", 0.0, 30.0, 70.0),
            _candidate("ob", 0.0, 30.0, 70.0),
            _candidate("oc", 0.0, 30.0, 70.0),
            _candidate("sd", 100.0, 130.0, 40.0),
            _candidate("se", 200.0, 230.0, 40.0),
            _candidate("sf", 300.0, 330.0, 40.0),
        ],
        top=6,
    )
    picked = [s["start"] for s in ranking["selected"]]
    # The crowded minute (0–60 s) contributes at most one selection.
    assert sum(0.0 <= start < 60.0 for start in picked) <= 1
    assert _ids(ranking)[0] == "oa"
    # A spaced alternative exists and is taken over a second same-minute clip.
    assert "sd" in _ids(ranking) and "se" in _ids(ranking)


# ---------------------------------------------------------------------------
# Labels / precision-recall (informational, deterministic)
# ---------------------------------------------------------------------------


def test_fixture_ranking_precision_recall_is_deterministic():
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    assert labels["schema"] == "ranking_labels"
    analysis = json.loads(ANALYSIS_SMALL.read_text(encoding="utf-8"))

    from scoria.score import score_candidates
    from scoria.segment import build_candidates

    cfg = build_config()
    scored = score_candidates(build_candidates(analysis, cfg), cfg, analysis_data=analysis)
    ranking = rank_candidates(scored, cfg, top=3)
    chosen = [s["id"] for s in ranking["selected"]]
    goods = {cid for cid, label in labels["labels"].items() if label == "good"}
    hits = sum(1 for cid in chosen if cid in goods)
    precision = hits / len(chosen) if chosen else 0.0
    recall = hits / len(goods) if goods else 0.0
    # Informational pins: report (not gate) the engine's top-3 vs human-labeled
    # goods (SCORING_ENGINE.md §8). Values frozen for determinism.
    assert chosen == ["c0006", "c0014"]
    assert precision == 1.0
    assert recall == pytest.approx(2 / 8)


# ---------------------------------------------------------------------------
# L5: `clipper rank`
# ---------------------------------------------------------------------------


def _write_project(tmp_path) -> Path:
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(json.dumps(json.loads(ANALYSIS_SMALL.read_text())), encoding="utf-8")
    candidates_path = tmp_path / "candidates.json"
    from scoria.segment import build_candidates

    candidates = build_candidates(json.loads(analysis_path.read_text()), build_config())
    candidates_path.write_text(dump_str(candidates), encoding="utf-8")
    return candidates_path


def test_cli_rank_writes_ranking_json(tmp_path):
    candidates = _write_project(tmp_path)
    scored = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert scored.exit_code == 0, scored.output
    result = runner.invoke(app, ["rank", str(candidates), "--top", "3", "--log-level", "error"])
    assert result.exit_code == 0, result.output
    ranking = json.loads((tmp_path / "ranking.json").read_text(encoding="utf-8"))
    assert ranking["schema"] == "ranking"
    assert [s["id"] for s in ranking["selected"]] == ["c0006", "c0014"]
    assert ranking["stopped"] is True
    assert check_contract(ranking) == []
    # gain_note explains the spacing decision for the 2nd pick.
    assert "spacing" in ranking["selected"][1]["gain_note"]


def test_cli_rank_accepts_project_dir(tmp_path):
    _write_project(tmp_path)
    runner.invoke(app, ["score", str(tmp_path), "--log-level", "error"])
    result = runner.invoke(app, ["rank", str(tmp_path), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "ranking.json").is_file()


def test_cli_rank_json_summary(tmp_path):
    candidates = _write_project(tmp_path)
    runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    result = runner.invoke(app, ["rank", str(candidates), "--json", "--log-level", "error"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.strip().splitlines()[-1])
    assert summary["selected"] == 2
    assert summary["stop_reason"] == "margin"
    assert summary["rank_version"] == RANK_VERSION


def test_cli_rank_requires_scored_candidates(tmp_path):
    candidates = _write_project(tmp_path)
    result = runner.invoke(app, ["rank", str(candidates), "--log-level", "error"])
    assert result.exit_code == 1
    assert "score" in result.output and "clipper score" in result.output


def test_cli_rank_rejects_non_candidates_doc(tmp_path):
    bogus = tmp_path / "candidates.json"
    bogus.write_text('{"schema": "analysis"}', encoding="utf-8")
    result = runner.invoke(app, ["rank", str(bogus), "--log-level", "error"])
    assert result.exit_code == 1
    assert "candidates" in result.output


def test_cli_rank_bad_config_exit_2(tmp_path):
    candidates = _write_project(tmp_path)
    runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    bad = tmp_path / "bad.yaml"
    bad.write_text("scoring:\n  ranking:\n    nope: 1.0\n", encoding="utf-8")
    result = runner.invoke(app, ["rank", str(candidates), "-c", str(bad), "--log-level", "error"])
    assert result.exit_code == 2


def test_cli_rank_determinism(tmp_path):
    candidates = _write_project(tmp_path)
    runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    first = runner.invoke(app, ["rank", str(candidates), "--log-level", "error"])
    assert first.exit_code == 0
    before = (tmp_path / "ranking.json").read_bytes()
    second = runner.invoke(app, ["rank", str(candidates), "--log-level", "error"])
    assert second.exit_code == 0
    assert (tmp_path / "ranking.json").read_bytes() == before
