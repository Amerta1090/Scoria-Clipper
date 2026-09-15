"""Sprint 5: scoring — math, term functions, penalties, golden totals, renorm.

L0 tests pin the pure curve/term/penalty functions; the golden fixture pins
per-candidate 4-decimal totals (computed below by the code itself, then frozen);
degraded-mode and re-score tests pin the deterministic renormalization and the
CLI_SPEC "candidates.json + config only" contract; L5 pins `clipper score`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import build_config
from scoria.project import check_contract, dump_str
from scoria.score import (
    SCORED_CANDIDATES_VERSION,
    smoothstep,
    trapezoid,
)
from scoria.score.features import normalize_token
from scoria.score.penalties import PENALTY_RULES
from scoria.score.pipeline import score_candidates
from scoria.score.terms import TERM_FUNCS
from scoria.segment import build_candidates

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS_SMALL = FIXTURES / "analysis_small.json"

runner = CliRunner()

# Golden per-candidate totals on analysis_small.json (default config, all signals
# present). Frozen by hand: model the openers/hook/bands against the fixture.
GOLDEN_TOTALS = {
    "c0001": 64.0449,
    "c0002": 32.8090,
    "c0003": 64.7387,
    "c0004": 32.8090,
    "c0005": 32.8090,
    "c0006": 75.2809,
    "c0007": 75.2809,
    "c0008": 75.2809,
    "c0009": 75.2809,
    "c0010": 75.2809,
    "c0011": 64.0449,
    "c0012": 42.8110,
    "c0013": 64.0449,
    "c0014": 64.0449,
}

DEFAULT_RENORM_FACTOR = 1.1236  # 1 / 0.89


def _cfg(**overrides):
    return build_config(overrides=overrides)


def _fixture_analysis():
    return json.loads(ANALYSIS_SMALL.read_text(encoding="utf-8"))


def _score(analysis, cfg, **kw):
    candidates = build_candidates(analysis, cfg)
    return score_candidates(candidates, cfg, analysis_data=analysis, **kw)


# ---------------------------------------------------------------------------
# L0: curve helpers
# ---------------------------------------------------------------------------


def test_smoothstep_hermite_shape():
    assert smoothstep(0.0, 0.0, 1.0) == 0.0
    assert smoothstep(1.0, 0.0, 1.0) == 1.0
    assert smoothstep(0.5, 0.0, 1.0) == 0.5  # 3(0.5)² − 2(0.5)³
    assert smoothstep(-1.0, 0.0, 1.0) == 0.0
    assert smoothstep(2.0, 0.0, 1.0) == 1.0
    assert smoothstep(0.7, 0.2, 0.8) == smoothstep(0.7, 0.2, 0.8)


def test_smoothstep_rejects_inverted_bounds():
    from scoria.score.math import smoothstep as ss

    with pytest.raises(ValueError):
        ss(0.5, 1.0, 0.0)


def test_trapezoid_flat_top_shape():
    assert trapezoid(0.0, 0.85, 1.0, 1.2, 1.5) == 0.0
    assert trapezoid(0.95, 0.85, 1.0, 1.2, 1.5) == pytest.approx(2 / 3)  # ramp 0→1
    assert trapezoid(1.1, 0.85, 1.0, 1.2, 1.5) == 1.0
    assert trapezoid(1.35, 0.85, 1.0, 1.2, 1.5) == pytest.approx(0.5)  # ramp 1→0
    assert trapezoid(1.5, 0.85, 1.0, 1.2, 1.5) == 0.0


def test_trapezoid_degenerate_ramps_jump():
    assert trapezoid(1.05, 0.85, 0.85, 1.2, 1.5) == 1.0
    assert trapezoid(1.05, 0.85, 1.0, 1.2, 1.2) == 1.0


# ---------------------------------------------------------------------------
# L0: term functions
# ---------------------------------------------------------------------------


def test_audio_energy_term():
    cfg = _cfg()
    s = TERM_FUNCS["audio_energy"]({"energy_ratio": 1.0}, cfg)
    assert s[1] == 1.0
    assert TERM_FUNCS["audio_energy"]({"energy_ratio": 0.0}, cfg)[1] == 0.0
    # 0.30 of R95 should sit between the 0.15/0.75 smoothstep bounds.
    assert 0.0 < TERM_FUNCS["audio_energy"]({"energy_ratio": 0.30}, cfg)[1] < 1.0


def test_speech_density_term():
    cfg = _cfg()
    full = TERM_FUNCS["speech_density"]({"speech_time_s": 40.0, "window_duration_s": 40.0}, cfg)
    assert full[1] == 1.0
    empty = TERM_FUNCS["speech_density"]({"speech_time_s": 0.0, "window_duration_s": 40.0}, cfg)
    assert empty[1] == 0.0


def test_pacing_term_uses_wpm_ratio_band():
    cfg = _cfg()
    # r = wpm / wpm_base in the 1.0–1.2 plateau → 1.0.
    assert TERM_FUNCS["pacing"]({"wpm": 115.0, "wpm_base": 100.0}, cfg)[1] == 1.0
    # r = 1.5 (at tail knot) → 0.0.
    assert TERM_FUNCS["pacing"]({"wpm": 150.0, "wpm_base": 100.0}, cfg)[1] == 0.0
    # No base → no pacing credit.
    assert TERM_FUNCS["pacing"]({"wpm": 120.0, "wpm_base": 0.0}, cfg)[1] == 0.0


def test_hook_open_short_question_and_burst():
    cfg = _cfg()
    short = {
        "first_sentence_text": "Singkat.",
        "first_sentence_words": 1,
        "window_words": [],
        "word_start_fractions": [],
        "energy_burst_ratio": 1.0,
    }
    assert TERM_FUNCS["hook"](short, cfg)[1] == 1.0

    question = {
        "first_sentence_text": "Apakah kamu suka?",
        "first_sentence_words": 4,
        "window_words": [],
        "word_start_fractions": [],
        "energy_burst_ratio": 0.0,
    }
    raw, normalized, note = TERM_FUNCS["hook"](question, cfg)
    assert normalized == 1.0
    assert "question" in note

    # Long question (past hook_max_first_sentence_words) is not an opener.
    long_question = {
        "first_sentence_text": "Apakah kalian semua ingin mengetahui sebuah rahasia besar yang "
        "akan mengubah cara hidup kita semua selamanya?",
        "first_sentence_words": 16,
        "window_words": [],
        "word_start_fractions": [],
        "energy_burst_ratio": 0.0,
    }
    assert TERM_FUNCS["hook"](long_question, cfg)[1] == 0.0


def test_hook_phrase_position_weighting():
    cfg = _cfg()
    phrase = list("yang perlu kamu tahu".split())
    # Match at fraction 0.0 → 1.0.
    at_start = {
        "first_sentence_text": "",
        "first_sentence_words": 0,
        "window_words": phrase,
        "word_start_fractions": [0.0, 0.0, 0.0, 0.0],
        "energy_burst_ratio": 0.0,
    }
    assert TERM_FUNCS["hook"](at_start, cfg)[1] == 1.0
    # Match at exactly the 30% boundary → 0.5.
    at_edge = {
        "first_sentence_text": "",
        "first_sentence_words": 0,
        "window_words": phrase,
        "word_start_fractions": [0.30, 0.30, 0.30, 0.30],
        "energy_burst_ratio": 0.0,
    }
    assert round(TERM_FUNCS["hook"](at_edge, cfg)[1], 6) == 0.5
    # Past 30% → capped at 0.5.
    beyond = {
        "first_sentence_text": "",
        "first_sentence_words": 0,
        "window_words": phrase,
        "word_start_fractions": [0.9, 0.9, 0.9, 0.9],
        "energy_burst_ratio": 0.0,
    }
    assert TERM_FUNCS["hook"](beyond, cfg)[1] == 0.5


def test_completeness_boundaries():
    cfg = _cfg()
    exact = TERM_FUNCS["completeness"](
        {
            "gap_start_ms": 0.0,
            "gap_end_ms": 0.0,
            "start_on_sentence": True,
            "end_on_sentence": True,
            "start_on_scene_or_silence": True,
            "end_on_scene_or_silence": True,
        },
        cfg,
    )
    assert exact[1] == 1.0

    mid_grade = TERM_FUNCS["completeness"](
        {
            "gap_start_ms": 200.0,
            "gap_end_ms": 200.0,
            "start_on_sentence": False,
            "end_on_sentence": False,
            "start_on_scene_or_silence": True,
            "end_on_scene_or_silence": True,
        },
        cfg,
    )
    assert mid_grade[1] == 0.5  # 0.5·0.5 + 0.5·0.5

    decay = TERM_FUNCS["completeness"](
        {
            "gap_start_ms": 1000.0,
            "gap_end_ms": 1000.0,
            "start_on_sentence": False,
            "end_on_sentence": False,
            "start_on_scene_or_silence": False,
            "end_on_scene_or_silence": False,
        },
        cfg,
    )
    assert round(decay[1], 4) == 0.5  # 0.5·0.5 + 0.5·0.5

    none = TERM_FUNCS["completeness"](
        {
            "gap_start_ms": None,
            "gap_end_ms": None,
            "start_on_sentence": False,
            "end_on_sentence": False,
            "start_on_scene_or_silence": False,
            "end_on_scene_or_silence": False,
        },
        cfg,
    )
    assert none[1] == 0.0


def test_visual_activity_noop():
    _, normalized, note = TERM_FUNCS["visual_activity"]({"scene_density": 1.9}, _cfg())
    assert normalized == 0.0
    assert "no-op" in note


def test_face_presence_noop():
    _, normalized, _ = TERM_FUNCS["face_presence"]({}, _cfg())
    assert normalized == 0.0


def test_keyword_density_single_and_phrase():
    cfg = _cfg()  # keywords: kunci tips cara tutorial review harga
    single = {
        "window_words": ["kunci", "kunci", "tips"],
        "window_duration_s": 60.0,
    }
    # 3 hits/min → right at the band high (3.0) → 1.0.
    assert round(TERM_FUNCS["keyword_density"](single, cfg)[1], 4) == 1.0

    multi = {
        "window_words": list("saya membeli harga murah".split()),
        "window_duration_s": 60.0,
    }
    s = TERM_FUNCS["keyword_density"](multi, cfg)[1]
    assert 0.0 < s < 1.0

    none = {"window_words": ["satu", "dua"], "window_duration_s": 30.0}
    assert TERM_FUNCS["keyword_density"](none, cfg)[1] == 0.0


def test_sentence_quality_band():
    cfg = _cfg()  # wlo6 lo9 hi18 whi22
    assert TERM_FUNCS["sentence_quality"]({"mean_wps": 12.0}, cfg)[1] == 1.0
    assert TERM_FUNCS["sentence_quality"]({"mean_wps": 4.0}, cfg)[1] == 0.0
    assert round(TERM_FUNCS["sentence_quality"]({"mean_wps": 7.5}, cfg)[1], 6) == 0.5
    assert round(TERM_FUNCS["sentence_quality"]({"mean_wps": 20.0}, cfg)[1], 6) == 0.5


def test_normalize_token():
    assert normalize_token("Yang!") == "yang"
    assert normalize_token("perlu") == "perlu"
    assert normalize_token("Água") == "gua"  # [^0-9a-z] stripped


# ---------------------------------------------------------------------------
# L0: penalties
# ---------------------------------------------------------------------------


def _cfg(**overrides):
    return build_config(overrides=overrides)


def test_penalty_leading_trailing_silence():
    firer = {"edge_silence": [[0.0, 0.6]], "candidate_start": 0.0}
    assert round(PENALTY_RULES["leading_silence"](firer, _cfg()), 4) == 0.10
    # Span shorter than edge_tolerance (0.4) at the edge → no penalty.
    too_short = {"edge_silence": [[0.0, 0.2]], "candidate_start": 0.0}
    assert PENALTY_RULES["leading_silence"](too_short, _cfg()) is None
    trailing = {"edge_silence": [[39.6, 40.4]], "candidate_end": 40.0}
    assert round(PENALTY_RULES["trailing_silence"](trailing, _cfg()), 4) == 0.10
    assert (
        PENALTY_RULES["trailing_silence"]({"edge_silence": [], "candidate_end": 40.0}, _cfg())
        is None
    )


def _edge_inputs(spans):
    return {"edge_silence": spans, "candidate_start": 0.0, "candidate_end": 40.0}


def test_penalty_dead_air_scaling():
    below = _edge_inputs([[5.0, 6.0]])  # 1s interior < dead_air 1.5
    assert PENALTY_RULES["dead_air"](below, _cfg()) is None
    # 3s interior dead air → scale (3−1.5)/1.5 = 1.0 → full cap.
    full = _edge_inputs([[4.0, 7.0]])
    assert round(PENALTY_RULES["dead_air"](full, _cfg()), 4) == 0.15
    # Partial: 2.25s → scale 0.5.
    partial = _edge_inputs([[4.0, 6.25]])
    assert round(PENALTY_RULES["dead_air"](partial, _cfg()), 4) == 0.075


def test_penalty_mid_sentence_start():
    fire = {
        "gap_start_ms": 2000.0,
        "inside_sentence": True,
        "start_on_sentence": False,
    }
    assert round(PENALTY_RULES["mid_sentence_start"](fire, _cfg()), 4) == 0.15
    under = {**fire, "gap_start_ms": 250.0}
    assert PENALTY_RULES["mid_sentence_start"](under, _cfg()) is None
    assert PENALTY_RULES["mid_sentence_start"]({**fire, "start_on_sentence": True}, _cfg()) is None
    assert PENALTY_RULES["mid_sentence_start"]({**fire, "inside_sentence": False}, _cfg()) is None


def test_penalty_mid_word_end():
    assert round(PENALTY_RULES["mid_word_end"]({"ends_inside_word": True}, _cfg()), 4) == 0.20
    assert PENALTY_RULES["mid_word_end"]({"ends_inside_word": False}, _cfg()) is None


def test_penalty_low_energy_tail():
    quiet = {"tail_mean_rms": 0.02, "clip_mean_rms": 0.10}
    assert round(PENALTY_RULES["low_energy_tail"](quiet, _cfg()), 4) == 0.05
    fine = {"tail_mean_rms": 0.04, "clip_mean_rms": 0.10}
    assert PENALTY_RULES["low_energy_tail"](fine, _cfg()) is None
    silent_clip = {"tail_mean_rms": 0.0, "clip_mean_rms": 0.0}
    assert PENALTY_RULES["low_energy_tail"](silent_clip, _cfg()) is None


def test_penalty_flub_repeats():
    flub = {"repeat_count": 3, "word_count": 300}
    assert round(PENALTY_RULES["flub_repeats"](flub, _cfg()), 4) == 0.05
    ok = {"repeat_count": 1, "word_count": 300}
    assert PENALTY_RULES["flub_repeats"](ok, _cfg()) is None
    assert PENALTY_RULES["flub_repeats"]({"repeat_count": 0, "word_count": 0}, _cfg()) is None


def test_penalty_peak_clipping():
    clipped = {"clip_fraction": 0.05}
    assert round(PENALTY_RULES["peak_clipping"](clipped, _cfg()), 4) == 0.02
    assert PENALTY_RULES["peak_clipping"]({"clip_fraction": 0.01}, _cfg()) is None


# ---------------------------------------------------------------------------
# L1: golden totals, bounds, renorm (fixture-pinned)
# ---------------------------------------------------------------------------


def _fixture_scored():
    return _score(_fixture_analysis(), _cfg())


def test_golden_totals_fixture_pinned():
    data = _fixture_scored()
    assert [(c["start"], c["end"]) for c in data["candidates"]] == [
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
    for candidate in data["candidates"]:
        assert candidate["score"]["total"] == GOLDEN_TOTALS[candidate["id"]]


def test_golden_breakdown_values():
    data = _fixture_scored()
    doc = next(c for c in data["candidates"] if c["id"] == "c0006")  # (12,70)
    score = doc["score"]
    assert score["renorm_factor"] == DEFAULT_RENORM_FACTOR
    assert round(score["subscore_sum"], 4) == 0.7528
    assert score["penalty_total"] == 0.0
    terms = {t["term"]: t for t in score["terms"]}
    assert [t["term"] for t in score["terms"]] == [
        "audio_energy",
        "speech_density",
        "pacing",
        "hook",
        "completeness",
        "visual_activity",
        "keyword_density",
        "sentence_quality",
    ]
    # completeness 1.0 × 0.20/0.89 — the heaviest term. Terms/breakdown are
    # serialized under the contract, so the stored values are 4-decimal.
    assert terms["completeness"]["weighted"] == round(0.20 / 0.89, 4)
    assert round(sum(t["weight"] for t in score["terms"]), 6) == 1.0
    # Hook, speech, audio, completeness are 1.0 on (12,70); pacing hits the plateau.
    for name in ("audio_energy", "speech_density", "hook", "completeness", "pacing"):
        assert terms[name]["normalized"] == 1.0, name
    # No-op visual contributes zero but stays in the breakdown.
    assert terms["visual_activity"]["normalized"] == 0.0
    assert terms["visual_activity"]["raw"] is None
    assert score["penalties"] == []


def test_golden_penalties_exist():
    data = _fixture_scored()
    by_range = {(c["start"], c["end"]): c for c in data["candidates"]}
    # (0,50) ends inside the word span starting at 48 → mid_word_end −0.20.
    p50 = by_range[(0.0, 50.0)]["score"]
    assert [p["rule"] for p in p50["penalties"]] == ["mid_word_end"]
    assert p50["penalty_total"] == 0.20
    # (50,80) starts mid-sentence (gap 2000ms > 300) → mid_sentence_start −0.15.
    p80 = by_range[(50.0, 80.0)]["score"]
    assert [p["rule"] for p in p80["penalties"]] == ["mid_sentence_start"]
    assert p80["penalty_total"] == 0.15
    # (70,120) is a clean sentence-to-end window.
    assert by_range[(70.0, 120.0)]["score"]["penalties"] == []


def test_bounds_every_normalized_in_range():
    data = _fixture_scored()
    for candidate in data["candidates"]:
        score = candidate["score"]
        assert 0.0 <= score["total"] <= 100.0
        assert score["subscore_sum"] >= 0.0
        for term in score["terms"]:
            assert 0.0 <= term["normalized"] <= 1.0
            assert 0.0 <= term["weight"] <= 1.0
        assert score["penalty_total"] <= 0.35


def test_golden_version_and_meta_stamped():
    data = _fixture_scored()
    assert data["version"] == SCORED_CANDIDATES_VERSION
    assert data["scoring_version"] == "1.0.0"
    assert data["scoring_meta"]["signals_disabled"] == []
    assert data["scoring_meta"]["renorm_factor"] == DEFAULT_RENORM_FACTOR


def test_golden_serializes_contract_clean():
    data = json.loads(dump_str(_fixture_scored()))
    assert check_contract(data) == []


def test_two_runs_identical():
    first = _fixture_scored()
    second = _score(_fixture_analysis(), _cfg())
    assert dump_str(first) == dump_str(second)


def test_reweight_renormalizes_and_reescores():
    cfg = _cfg(scoring={"weights": {"completeness": 0.30, "hook": 0.10}})
    data = _score(_fixture_analysis(), cfg)
    # Enabled set: hoop/visual/keyword/speech/pacing/audio keep defaults, so the
    # raw sum becomes 0.94 (was 0.89) and every display weight renormalizes.
    terms = {t["term"]: t for t in data["candidates"][0]["score"]["terms"]}
    assert terms["completeness"]["weight"] == round(0.30 / 0.94, 4)
    assert terms["hook"]["weight"] == round(0.10 / 0.94, 4)
    assert data["candidates"][0]["score"]["renorm_factor"] == round(1.0 / 0.94, 4)


# ---------------------------------------------------------------------------
# L1: config-only re-score (embedded inputs)
# ---------------------------------------------------------------------------


def test_reescore_from_embedded_is_byte_identical():
    data = _fixture_scored()
    assert dump_str(data) == dump_str(score_candidates(data, _cfg()))


def test_reescore_respects_embedded_signals_disabled():
    analysis = _fixture_analysis()
    analysis["transcript"] = None
    data = _score(analysis, _cfg())
    assert data["scoring_meta"]["signals_disabled"] == ["transcript"]
    rescored = score_candidates(data, _cfg())
    assert dump_str(data) == dump_str(rescored)


def test_no_transcript_pure_energy_renorm():
    analysis = _fixture_analysis()
    analysis["transcript"] = None
    data = _score(analysis, _cfg())
    assert data["scoring_meta"]["signals_disabled"] == ["transcript"]
    # Enabled terms = audio_energy (0.09) + visual_activity (0.10) → 1/0.19.
    assert round(data["scoring_meta"]["renorm_factor"], 4) == 5.2632
    terms = {t["term"]: t for t in data["candidates"][0]["score"]["terms"]}
    assert set(terms) == {"audio_energy", "visual_activity"}
    # 100 × (0.09/0.19 × 1.0) − 0 → 47.3684.
    assert round(data["candidates"][0]["score"]["total"], 4) == 47.3684


def test_no_visual_renormalizes_visual_activity_out():
    analysis = _fixture_analysis()
    analysis["visual"] = None
    data = _score(analysis, _cfg())
    assert data["scoring_meta"]["signals_disabled"] == ["visual"]
    terms = {t["term"]: t for t in data["candidates"][0]["score"]["terms"]}
    assert "visual_activity" not in terms
    assert round(sum(v["weight"] for v in terms.values()), 6) == 1.0


def test_both_off_graceful_floor():
    analysis = _fixture_analysis()
    analysis["transcript"] = None
    analysis["visual"] = None
    # Only silence boundaries survive segmentation; the first candidate anchors at
    # (30, 90) and its leading span fills the full edge zone (exact-tol fill) —
    # pinning that edge rule also guards the epsilon comparison in the penalty.
    analysis["audio"]["silence"] = [{"start": 30.0, "end": 31.0, "duration": 1.0}]
    data = _score(analysis, _cfg())
    assert data["scoring_meta"]["signals_disabled"] == ["transcript", "visual"]
    first = data["candidates"][0]["score"]
    terms = {t["term"]: t for t in first["terms"]}
    assert set(terms) == {"audio_energy"}
    assert first["renorm_factor"] == round(1.0 / 0.09, 4)  # audio weight only
    assert first["penalty_total"] == 0.10  # leading_silence at exact-tol cover
    assert round(first["total"], 4) == 100.0 * (1.0 - 0.10)


def test_penalty_caps_respected():
    analysis = _fixture_analysis()
    analysis["audio"]["silence"] = [
        {"start": 0.0, "end": 4.0, "duration": 4.0},  # leading_silence
        {"start": 36.0, "end": 40.0, "duration": 4.0},  # trailing + dead_air
    ]
    data = _score(analysis, _cfg())
    score = next(c["score"] for c in data["candidates"] if (c["start"], c["end"]) == (0.0, 40.0))
    # leading 0.10 + trailing 0.10 + dead_air 0.15 == the 0.35 total cap.
    assert score["penalty_total"] == 0.35


# ---------------------------------------------------------------------------
# L5: `clipper score` CLI
# ---------------------------------------------------------------------------


def _write_project(tmp_path, **overrides_analysis):
    analysis = _fixture_analysis()
    analysis.update(overrides_analysis)
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    candidates = build_candidates(json.loads(analysis_path.read_text()), _cfg())
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(dump_str(candidates), encoding="utf-8")
    return analysis_path, candidates_path


def test_cli_score_writes_enriched_doc(tmp_path):
    _, candidates = _write_project(tmp_path)
    result = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    data = json.loads(candidates.read_text(encoding="utf-8"))
    assert data["version"] == SCORED_CANDIDATES_VERSION
    assert all("score" in c for c in data["candidates"])
    assert candidates.read_text(encoding="utf-8") == dump_str(data) + "\n"
    assert check_contract(data) == []


def test_cli_score_accepts_project_dir(tmp_path):
    _write_project(tmp_path)
    result = runner.invoke(app, ["score", str(tmp_path), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert data["candidates"][0]["score"]["total"] == GOLDEN_TOTALS["c0001"]


def test_cli_score_re_score_is_deterministic(tmp_path):
    _, candidates = _write_project(tmp_path)
    first = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert first.exit_code == 0
    before = candidates.read_bytes()
    second = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert second.exit_code == 0, second.output
    assert candidates.read_bytes() == before


def test_cli_score_needs_sibling_analysis_on_first_pass(tmp_path):
    _, candidates = _write_project(tmp_path)
    (tmp_path / "analysis.json").unlink()
    result = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert result.exit_code == 1
    assert "analysis.json" in result.output
    # A re-score of an enriched doc needs no analysis.json.
    (tmp_path / "analysis.json").write_text(dump_str(_fixture_analysis()), encoding="utf-8")
    runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    (tmp_path / "analysis.json").unlink()
    result = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert result.exit_code == 0, result.output


def test_cli_score_json_summary(tmp_path):
    _, candidates = _write_project(tmp_path)
    result = runner.invoke(app, ["score", str(candidates), "--log-level", "error", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.strip().splitlines()[-1])
    assert summary["candidates"] == 14
    assert summary["scoring_version"] == "1.0.0"


def test_cli_score_rejects_non_candidates_doc(tmp_path):
    bogus = tmp_path / "candidates.json"
    bogus.write_text('{"schema": "analysis"}', encoding="utf-8")
    result = runner.invoke(app, ["score", str(bogus), "--log-level", "error"])
    assert result.exit_code == 1
    assert "candidates" in result.output


def test_cli_bad_config_exit_2(tmp_path):
    _, candidates = _write_project(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("scoring:\n  weights:\n    nope: 0.5\n", encoding="utf-8")
    result = runner.invoke(app, ["score", str(candidates), "-c", str(bad), "--log-level", "error"])
    assert result.exit_code == 2
