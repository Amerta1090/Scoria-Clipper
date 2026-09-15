"""Scoring output models: the per-candidate `ScoreBreakdown`.

Each candidate in the enriched `candidates.json` carries one `ScoreBreakdown`
(SCORING_ENGINE.md §1): one `TermScore` per enabled sub-score and one
`PenaltyScore` per applied penalty. Every entry embeds its `inputs` so a
config-only re-score can re-derive the breakdown from `candidates.json` alone
(CLI_SPEC.md: `clipper score` is a deterministic function of candidates +
config). The enriched document bumps `CANDIDATES_VERSION` to
`SCORED_CANDIDATES_VERSION` and stamps `scoring_version`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Enriched candidates document version (raw segment output is version 1).
SCORED_CANDIDATES_VERSION = 2

# Function ids stamped per term — the deterministic record of *which* formula
# produced a number (SCORING_ENGINE.md §1). Bumped whenever a term changes.
FUNCTION_IDS: dict[str, str] = {
    "audio_energy": "energy.mean_clamp.smoothstep.v1",
    "speech_density": "speech.overlap_ratio.smoothstep.v1",
    "pacing": "pacing.wpm_trapezoid.v1",
    "hook": "hook.max_openers.v1",
    "completeness": "completeness.sentence_align.v1",
    "visual_activity": "visual_activity.noop.v1",
    "keyword_density": "keywords.hits_min.smoothstep.v1",
    "sentence_quality": "sentence_quality.wps_trapezoid.v1",
}

PENALTY_FUNCTION_IDS: dict[str, str] = {
    "leading_silence": "penalty.edge_silence.v1",
    "trailing_silence": "penalty.edge_silence.v1",
    "dead_air": "penalty.dead_air.v1",
    "mid_sentence_start": "penalty.mid_sentence_start.v1",
    "mid_word_end": "penalty.mid_word_end.v1",
    "low_energy_tail": "penalty.low_energy_tail.v1",
    "flub_repeats": "penalty.flub_repeats.v1",
    "peak_clipping": "penalty.peak_clipping.v1",
}


class TermScore(BaseModel):
    term: str
    function: str
    inputs: dict[str, Any]
    raw: float | None
    normalized: float
    weight: float
    weighted: float
    note: str


class PenaltyScore(BaseModel):
    rule: str
    function: str
    inputs: dict[str, Any]
    value: float
    note: str


class ScoreBreakdown(BaseModel):
    total: float
    subscore_sum: float
    penalty_total: float
    renorm_factor: float
    terms: list[TermScore]
    penalties: list[PenaltyScore]


class ScoringMeta(BaseModel):
    """Document-level scoring stamp: version + which signals were disabled so a
    later re-score reproduces the same enabled/renormalized weight set."""

    scoring_version: str
    signals_disabled: list[str] = Field(default_factory=list)
    renorm_factor: float
