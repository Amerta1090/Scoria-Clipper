"""Penalty rules (SCORING_ENGINE.md §3).

Each rule is a deterministic `(inputs, config) → value | None` — `None` means
the rule did not fire. Values are `−value` in [0,1], capped per rule at the
config cap; the pipeline caps the sum at `scoring.penalties.total_cap`. The
constant thresholds (300 ms mid-sentence, 30 % low-energy tail, 0.5 % flub,
2 % clipping) come straight from SCORING_ENGINE §3 — they are spec numerals,
not config.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scoria.config.schema import ScoriaConfig

MID_SENTENCE_TOL_MS = 300.0
LOW_ENERGY_RATIO = 0.3
FLUB_REPEAT_RATIO = 0.005
CLIP_FRACTION_THRESHOLD = 0.02
# Fractional slack so a span that exactly fills the edge zone (tol is a 4-decimal
# float; 40.0 - 39.6 == 0.3999...) still fires the edge-silence rule.
_EDGE_EPS = 1e-9


def _edge_cover(spans: list[list[float]], point: float, tol: float, *, front: bool) -> float:
    """Longest overlap a silence span has with the [point, point+tol] zone."""
    zone_lo = point if front else point - tol
    zone_hi = point + tol if front else point
    best = 0.0
    for s, e in spans:
        overlap = min(e, zone_hi) - max(s, zone_lo)
        best = max(best, overlap)
    return max(best, 0.0)


def _edge_penalty(inputs: dict[str, Any], config: ScoriaConfig, *, front: bool) -> float | None:
    spans = inputs.get("edge_silence", [])
    point = float(inputs.get("candidate_start" if front else "candidate_end", 0.0))
    tol = config.audio.silence.edge_tolerance
    if tol <= 0.0:
        return None
    cover = _edge_cover(spans, point, tol, front=front)
    # "silence ≥ edge_tolerance at the edge" — a span must fill the whole zone.
    if cover < tol - _EDGE_EPS:
        return None
    return config.scoring.penalties.caps.edge_silence


def penalty_leading_silence(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    return _edge_penalty(inputs, config, front=True)


def penalty_trailing_silence(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    return _edge_penalty(inputs, config, front=False)


def penalty_dead_air(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    spans = inputs.get("edge_silence", [])
    start = float(inputs.get("candidate_start", 0.0))
    end = float(inputs.get("candidate_end", 0.0))
    tol = config.audio.silence.edge_tolerance
    threshold = config.audio.silence.dead_air
    cap = config.scoring.penalties.caps.dead_air

    zone_lo = start + tol
    zone_hi = end - tol
    if zone_hi <= zone_lo:
        return None
    total = 0.0
    for s, e in spans:
        total += max(0.0, min(e, zone_hi) - max(s, zone_lo))
    if total <= threshold:
        return None
    scale = min(1.0, (total - threshold) / threshold)
    return cap * scale


def penalty_mid_sentence_start(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    if inputs.get("start_on_sentence", False):
        return None
    if not inputs.get("inside_sentence", False):
        return None
    gap = inputs.get("gap_start_ms")
    if gap is None or float(gap) <= MID_SENTENCE_TOL_MS:
        return None
    return config.scoring.penalties.caps.mid_sentence


def penalty_mid_word_end(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    if not inputs.get("ends_inside_word", False):
        return None
    return config.scoring.penalties.caps.mid_word


def penalty_low_energy_tail(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    tail = float(inputs.get("tail_mean_rms", 0.0))
    clip = float(inputs.get("clip_mean_rms", 0.0))
    if clip <= 0.0 or tail >= LOW_ENERGY_RATIO * clip:
        return None
    return config.scoring.penalties.caps.tail


def penalty_flub_repeats(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    repeats = int(inputs.get("repeat_count", 0))
    words = int(inputs.get("word_count", 0))
    if words <= 0:
        return None
    if repeats / words < FLUB_REPEAT_RATIO:
        return None
    return config.scoring.penalties.caps.flub


def penalty_peak_clipping(inputs: dict[str, Any], config: ScoriaConfig) -> float | None:
    fraction = float(inputs.get("clip_fraction", 0.0))
    if fraction <= CLIP_FRACTION_THRESHOLD:
        return None
    return config.scoring.penalties.caps.clip


PENALTY_RULES: dict[str, Callable[[dict[str, Any], ScoriaConfig], float | None]] = {
    "leading_silence": penalty_leading_silence,
    "trailing_silence": penalty_trailing_silence,
    "dead_air": penalty_dead_air,
    "mid_sentence_start": penalty_mid_sentence_start,
    "mid_word_end": penalty_mid_word_end,
    "low_energy_tail": penalty_low_energy_tail,
    "flub_repeats": penalty_flub_repeats,
    "peak_clipping": penalty_peak_clipping,
}
