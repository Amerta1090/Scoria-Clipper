"""Scoring: normalized sub-scores, weights, penalties, breakdowns (SCORING_ENGINE.md).

`score_candidates` is the Sprint 5 entry point: it builds per-candidate feature
inputs from analysis.json (first pass) or the embedded inputs (config-only
re-score), applies the renormalized weights and capped penalties, and returns the
enriched candidates document with one `ScoreBreakdown` per candidate.
"""

from scoria.score.features import CandidateFeatures, build_candidate_features, normalize_token
from scoria.score.math import smoothstep, trapezoid
from scoria.score.models import (
    FUNCTION_IDS,
    PENALTY_FUNCTION_IDS,
    SCORED_CANDIDATES_VERSION,
    PenaltyScore,
    ScoreBreakdown,
    ScoringMeta,
    TermScore,
)
from scoria.score.penalties import PENALTY_RULES
from scoria.score.pipeline import score_candidates
from scoria.score.terms import TERM_FUNCS

__all__ = [
    "SCORED_CANDIDATES_VERSION",
    "FUNCTION_IDS",
    "PENALTY_FUNCTION_IDS",
    "PENALTY_RULES",
    "TERM_FUNCS",
    "CandidateFeatures",
    "PenaltyScore",
    "ScoreBreakdown",
    "ScoringMeta",
    "TermScore",
    "build_candidate_features",
    "normalize_token",
    "score_candidates",
    "smoothstep",
    "trapezoid",
]
