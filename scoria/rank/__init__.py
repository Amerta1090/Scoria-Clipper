"""Ranking: diversity-aware greedy top-N (SCORING_ENGINE.md §7, ADR-006/ADR-017).

`rank_candidates` is the Sprint 6 entry point: pure greedy marginal-gain selection
over the enriched candidates document, returning the `ranking.json` document —
selected top-N with per-chosen rationale plus the full per-step marginal-gain
decision log so `explain` can say why a candidate was dropped.
"""

from scoria.rank.models import (
    RANK_VERSION,
    RANKING_SCHEMA,
    RANKING_VERSION,
    MarginalRecord,
    RankingConfigSnapshot,
    RankingInfo,
    RankingStep,
    RejectedClip,
    SelectedClip,
)
from scoria.rank.pipeline import rank_candidates

__all__ = [
    "RANK_VERSION",
    "RANKING_SCHEMA",
    "RANKING_VERSION",
    "MarginalRecord",
    "RankingConfigSnapshot",
    "RankingInfo",
    "RankingStep",
    "RejectedClip",
    "SelectedClip",
    "rank_candidates",
]
