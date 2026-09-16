"""Ranking: diverse greedy top-N with marginal gain (SCORING_ENGINE.md §7, ADR-006).

`rank_candidates` is a pure function of the enriched candidates document +
config: candidates.json → ranking.json. No I/O, no RNG — the same input produces
the byte-identical ranking artifact, which is what Sprint 6's determinism run
pins.

Algorithm (ADR-017 pins the scale): order by (score desc, start asc, id asc);
per greedy step G(c) = total(c) − ov_pen − sim_pen − gap_pen, all in score-units
(0–100):

- ov_pen  = 100·λ_ov·min(1, Σ overlap seconds over chosen / duration) — a fully
  overlapping clip loses its whole score.
- sim_pen = 100·λ_sim·max over chosen of Jaccard(normalized token sets) — exact
  term overlap only, semantic-free.
- gap_pen = 100·λ_gap·clamp((preferred_gap − actual_gap)/preferred_gap, 0, 1),
  preferred_gap = preferred_gap_factor·duration, actual_gap = distance to the
  nearest chosen interval.
- Select the argmax G if its G ≥ min_margin, else stop. Ties resolve by
  (start asc, id asc), ARCHITECTURE.md §7.

`hard_min_start_gap` is a hard rule: a candidate whose start sits within that
gap of any chosen start is excluded outright this step (recorded, not scored).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scoria.config.schema import ScoriaConfig
from scoria.errors import PipelineError
from scoria.project.jsonio import normalize
from scoria.rank.models import (
    RANK_VERSION,
    MarginalRecord,
    RankingConfigSnapshot,
    RankingInfo,
    RankingStep,
    RejectedClip,
    SelectedClip,
)
from scoria.segment.models import CandidatesInfo

_EXCLUDED_HARD_GAP = "hard_start_gap"


@dataclass
class _Plan:
    """Per-candidate selection view. Frozen after construction."""

    candidate_id: str
    start: float
    end: float
    duration: float
    score: float
    tokens: frozenset[str] = field(default_factory=frozenset)
    gain: float | None = None
    excluded: str | None = None
    overlap_seconds: float = 0.0
    overlap_penalty: float = 0.0
    jaccard_max: float = 0.0
    sim_penalty: float = 0.0
    gap: float | None = None
    gap_penalty: float = 0.0
    note: str = ""


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _interval_distance(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Min gap in seconds between two closed intervals (0 when overlapping)."""
    return max(0.0, b_start - a_end, a_start - b_end)


def _evaluate(candidate: _Plan, chosen: list[_Plan], config: ScoriaConfig) -> _Plan:
    ranking = config.scoring.ranking
    if ranking.hard_min_start_gap > 0.0 and any(
        abs(candidate.start - ch.start) < ranking.hard_min_start_gap for ch in chosen
    ):
        return _Plan(
            candidate_id=candidate.candidate_id,
            start=candidate.start,
            end=candidate.end,
            duration=candidate.duration,
            score=candidate.score,
            tokens=candidate.tokens,
            excluded=_EXCLUDED_HARD_GAP,
            note=(
                f"excluded: start within hard_min_start_gap "
                f"{ranking.hard_min_start_gap:.2f}s of a chosen start"
            ),
        )

    if not chosen:
        return _Plan(
            candidate_id=candidate.candidate_id,
            start=candidate.start,
            end=candidate.end,
            duration=candidate.duration,
            score=candidate.score,
            tokens=candidate.tokens,
            gain=candidate.score,
            note="no penalties (first selection)",
        )

    overlap_seconds = 0.0
    jaccard_max = 0.0
    gap_nearest: float | None = None
    denom = candidate.duration if candidate.duration > 0.0 else 1.0
    for ch in chosen:
        overlap = max(0.0, min(candidate.end, ch.end) - max(candidate.start, ch.start))
        overlap_seconds += overlap
        jaccard_max = max(jaccard_max, _jaccard(candidate.tokens, ch.tokens))
        gap = _interval_distance(candidate.start, candidate.end, ch.start, ch.end)
        gap_nearest = gap if gap_nearest is None else min(gap_nearest, gap)

    overlap_penalty = 100.0 * ranking.lam_overlap * min(1.0, overlap_seconds / denom)
    sim_penalty = 100.0 * ranking.lam_similarity * jaccard_max
    preferred_gap = ranking.preferred_gap_factor * candidate.duration
    gap_ratio = 0.0
    if preferred_gap > 0.0 and gap_nearest is not None:
        gap_ratio = max(0.0, min(1.0, (preferred_gap - gap_nearest) / preferred_gap))
    gap_penalty = 100.0 * ranking.lam_gap * gap_ratio
    gain = candidate.score - overlap_penalty - sim_penalty - gap_penalty

    dominant, note = _dominant_note(overlap_penalty, sim_penalty, gap_penalty)
    return _Plan(
        candidate_id=candidate.candidate_id,
        start=candidate.start,
        end=candidate.end,
        duration=candidate.duration,
        score=candidate.score,
        tokens=candidate.tokens,
        gain=gain,
        overlap_seconds=overlap_seconds,
        overlap_penalty=overlap_penalty,
        jaccard_max=jaccard_max,
        sim_penalty=sim_penalty,
        gap=gap_nearest,
        gap_penalty=gap_penalty,
        note=f"dominant penalty {dominant} ({note:.2f})",
    )


def _dominant_note(overlap: float, sim: float, gap: float) -> tuple[str, float]:
    if gap >= overlap and gap >= sim:
        return "gap", gap
    if sim >= overlap:
        return "similarity", sim
    return "overlap", overlap


def _gain_note(plan: _Plan, step: int, margin: float) -> str:
    if step == 1:
        return f"selected first: highest score ({plan.score:.4f})"
    if plan.gap_penalty >= plan.sim_penalty and plan.gap_penalty >= plan.overlap_penalty:
        if plan.gap_penalty > 0.0:
            return (
                f"best marginal gain {plan.gain:.4f}: dominant penalty gap "
                f"({plan.gap_penalty:.2f}, spacing {plan.gap:.1f}s)"
            )
        return f"best marginal gain {plan.gain:.4f}: no penalties vs chosen"
    if plan.sim_penalty >= plan.overlap_penalty:
        return (
            f"best marginal gain {plan.gain:.4f}: dominant penalty similarity "
            f"({plan.sim_penalty:.2f}, Jaccard {plan.jaccard_max:.3f})"
        )
    return (
        f"best marginal gain {plan.gain:.4f}: dominant penalty overlap "
        f"({plan.overlap_penalty:.2f}, {plan.overlap_seconds:.1f}s of {plan.duration:.1f}s)"
    )


def _extract_plan(candidates_data: dict) -> list[_Plan]:
    info = CandidatesInfo.model_validate(candidates_data)
    by_id = {
        str(entry.get("id")): entry for entry in candidates_data.get("candidates", []) if entry
    }
    plans: list[_Plan] = []
    for candidate in info.candidates:
        score_block = (by_id.get(candidate.id) or {}).get("score")
        if not isinstance(score_block, dict) or not isinstance(
            score_block.get("total"), (int, float)
        ):
            raise PipelineError(
                f"candidate {candidate.id} has no embedded ScoreBreakdown — ranking needs "
                "scored candidates",
                hint="run `clipper score` first, then `clipper rank`",
            )
        tokens: frozenset[str] = frozenset()
        for term in score_block.get("terms", []):
            if isinstance(term, dict) and term.get("term") == "keyword_density":
                words = term.get("inputs", {}).get("window_words")
                if isinstance(words, list):
                    tokens = frozenset(str(w) for w in words)
        plans.append(
            _Plan(
                candidate_id=candidate.id,
                start=candidate.start,
                end=candidate.end,
                duration=candidate.duration,
                score=float(score_block["total"]),
                tokens=tokens,
            )
        )
    plans.sort(key=lambda p: (-p.score, p.start, p.candidate_id))
    return plans


def rank_candidates(candidates_data: dict, config: ScoriaConfig, top: int) -> dict:
    """Build the ranking document from the enriched candidates.json (§7 greedy).

    `candidates_data` must be the *enriched* (Sprint 5) document: every candidate
    carries an embedded `ScoreBreakdown`. `top` is the requested selection size;
    selection stops early when the best marginal gain drops below
    `scoring.ranking.min_margin`.
    """

    ranking = config.scoring.ranking
    snapshot = RankingConfigSnapshot(
        min_margin=ranking.min_margin,
        lam_overlap=ranking.lam_overlap,
        lam_similarity=ranking.lam_similarity,
        lam_gap=ranking.lam_gap,
        preferred_gap_factor=ranking.preferred_gap_factor,
        hard_min_start_gap=ranking.hard_min_start_gap,
    )
    base = dict(
        rank_version=RANK_VERSION,
        top=top,
        enabled=ranking.enabled,
        min_margin=ranking.min_margin,
        config=snapshot,
        selected=[],
        rejected=[],
        decisions=[],
    )

    if not ranking.enabled:
        base.update(
            stopped=False,
            stop_reason=None,
            note="ranking disabled by config (scoring.ranking.enabled=false)",
        )
        return RankingInfo(**base).model_dump(mode="json", by_alias=True)

    if top <= 0:
        base.update(stopped=False, stop_reason=None, note=f"top <= 0 ({top}): nothing selected")
        return RankingInfo(**base).model_dump(mode="json", by_alias=True)

    pool = _extract_plan(candidates_data)
    all_plans = list(pool)
    chosen: list[_Plan] = []
    selected: list[SelectedClip] = []
    decisions: list[RankingStep] = []
    histories: dict[str, list[tuple[int, float]]] = {p.candidate_id: [] for p in pool}

    stop_reason = None
    for step in range(1, top + 1):
        if not pool:
            stop_reason = "exhausted"
            break

        evaluated = [_evaluate(c, chosen, config) for c in pool]
        eligible = [e for e in evaluated if e.excluded is None]
        for e in evaluated:
            if e.gain is not None:
                histories[e.candidate_id].append((step, e.gain))

        records = [_record(e) for e in evaluated]
        decisions.append(
            RankingStep(
                step=step,
                selected=None,
                selected_gain=None,
                candidates=records,
            )
        )

        if not eligible:
            stop_reason = "exhausted"
            break

        best = min(eligible, key=lambda e: (-(e.gain or 0.0), e.start, e.candidate_id))
        if best.gain is None or best.gain < ranking.min_margin:
            stop_reason = "margin"
            break

        chosen.append(best)
        decisions[-1].selected = best.candidate_id
        decisions[-1].selected_gain = best.gain
        selected.append(
            SelectedClip(
                id=best.candidate_id,
                rank=step,
                start=best.start,
                end=best.end,
                duration=best.duration,
                score=best.score,
                gain=best.gain,
                gain_note=_gain_note(best, step, ranking.min_margin),
                overlap_seconds=best.overlap_seconds,
                overlap_penalty=best.overlap_penalty,
                jaccard_max=best.jaccard_max,
                sim_penalty=best.sim_penalty,
                gap=best.gap,
                gap_penalty=best.gap_penalty,
            )
        )
        pool = [p for p in pool if p.candidate_id != best.candidate_id]

    if stop_reason is None:
        stop_reason = "top" if len(selected) == top else "exhausted"

    rejected = _build_rejected(
        all_plans,
        selected,
        histories,
        stop_reason,
        ranking.min_margin,
        top,
    )

    base.update(
        stopped=stop_reason in ("margin", "exhausted"),
        stop_reason=stop_reason,
        selected=selected,
        rejected=rejected,
        decisions=decisions,
    )
    return normalize(RankingInfo(**base).model_dump(mode="json", by_alias=True))


def _record(plan: _Plan) -> MarginalRecord:
    return MarginalRecord(
        id=plan.candidate_id,
        gain=plan.gain,
        overlap_seconds=plan.overlap_seconds,
        overlap_penalty=plan.overlap_penalty,
        jaccard_max=plan.jaccard_max,
        sim_penalty=plan.sim_penalty,
        gap=plan.gap,
        gap_penalty=plan.gap_penalty,
        excluded=plan.excluded,
        note=plan.note,
    )


def _build_rejected(
    plans: list[_Plan],
    selected: list[SelectedClip],
    histories: dict[str, list[tuple[int, float]]],
    stop_reason: str,
    margin: float,
    top: int,
) -> list[RejectedClip]:
    selected_ids = {s.id for s in selected}
    out: list[RejectedClip] = []
    for plan in plans:
        if plan.candidate_id in selected_ids:
            continue
        history = histories[plan.candidate_id]
        step_best, best_gain = history[0]
        last_step, last_gain = history[-1]
        out.append(
            RejectedClip(
                id=plan.candidate_id,
                score=plan.score,
                best_gain=best_gain,
                step=step_best,
                reason=_rejection_reason(stop_reason, last_gain, margin, top, last_step),
            )
        )
    out.sort(key=lambda r: (r.step, r.id))
    return out


def _rejection_reason(
    stop_reason: str, last_gain: float, margin: float, top: int, last_step: int
) -> str:
    if stop_reason == "margin":
        return (
            f"below min_margin {margin:.2f} at step {last_step} "
            f"(last marginal gain {last_gain:.4f})"
        )
    if stop_reason == "exhausted":
        return "selection exhausted before quota reached"
    return f"rank quota filled at step {last_step} (top {top})"
