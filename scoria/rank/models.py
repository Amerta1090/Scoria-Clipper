"""Ranking output models: the `ranking.json` document (SCORING_ENGINE.md §7).

`clipper rank` runs the greedy marginal-gain selection over the enriched
candidates document and writes this artifact: the selected top-N with per-chosen
rationale (`gain_note`, the penalty decomposition that picked it) plus the full
marginal-gain decision log — every candidate's G(c) at every greedy step — so
`explain` can show exactly why a candidate was rejected. All float columns are
normalized to the 4-decimal serialization contract (ADR-010) on write.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RANKING_SCHEMA = "ranking"
RANKING_VERSION = 1

# Function id stamped on the document — the deterministic record of *which*
# selection procedure produced it (mirrors SCORING_ENGINE.md FUNCTION_IDS).
RANK_VERSION = "greedy.marginal_gain.v1"


class RankingConfigSnapshot(BaseModel):
    """The ranking lens (`scoring.ranking.*`) that produced this document."""

    min_margin: float
    lam_overlap: float
    lam_similarity: float
    lam_gap: float
    preferred_gap_factor: float
    hard_min_start_gap: float


class MarginalRecord(BaseModel):
    """One candidate's marginal gain G(c) at one greedy step (score-units).

    Penalties are `100 * lambda * normalized_ratio` on the 0–100 score scale
    (ADR-017): a fully overlapping clip loses its whole score, and min_margin is
    directly comparable to `total`. `excluded` marks hard-rule rejections
    (`hard_min_start_gap`) where G is not computed.
    """

    id: str
    gain: float | None
    overlap_seconds: float
    overlap_penalty: float
    jaccard_max: float
    sim_penalty: float
    gap: float | None
    gap_penalty: float
    excluded: str | None = None
    note: str


class RankingStep(BaseModel):
    """One greedy iteration: the chosen candidate + every pool member's G."""

    step: int
    selected: str | None
    selected_gain: float | None
    candidates: list[MarginalRecord]


class SelectedClip(BaseModel):
    id: str
    rank: int
    start: float
    end: float
    duration: float
    score: float
    gain: float
    gain_note: str
    overlap_seconds: float
    overlap_penalty: float
    jaccard_max: float
    sim_penalty: float
    gap: float | None
    gap_penalty: float


class RejectedClip(BaseModel):
    """A candidate that never made the cut, with its best opportunity."""

    id: str
    score: float
    best_gain: float
    step: int
    reason: str


class RankingInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["ranking"] = Field(RANKING_SCHEMA, alias="schema")
    version: int = RANKING_VERSION
    rank_version: str = RANK_VERSION
    top: int
    enabled: bool
    stopped: bool
    stop_reason: str | None
    min_margin: float
    config: RankingConfigSnapshot
    selected: list[SelectedClip]
    rejected: list[RejectedClip]
    decisions: list[RankingStep]
    note: str = ""
