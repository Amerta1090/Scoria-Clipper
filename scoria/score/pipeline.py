"""Scoring pipeline: candidates.json + config (+ analysis.json on the first pass)
→ enriched candidates document (SCORING_ENGINE.md §1, CLI_SPEC.md `clipper score`).

First pass: a raw `candidates.json` (version 1) has no embedded term inputs, so
`build_candidate_features` reads the sibling `analysis.json`. The enriched output
stamps every term/penalty with its `inputs`, making every later pass a pure
function of candidates.json + config — re-running `clipper score proj/candidates.json
-c tuned.yaml` needs no analysis artifact. The document version bumps to
`SCORED_CANDIDATES_VERSION` and `scoring_version` is stamped from config.
"""

from __future__ import annotations

from typing import Any

from scoria.config.schema import _WEIGHT_FIELDS, TRANSCRIPT_DISABLED_TERMS, ScoriaConfig
from scoria.errors import PipelineError
from scoria.project.jsonio import normalize
from scoria.score.features import CandidateFeatures, build_candidate_features
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
from scoria.score.terms import TERM_FUNCS
from scoria.segment.models import CandidatesInfo

_PENALTY_ROW = (
    "leading_silence",
    "trailing_silence",
    "dead_air",
    "mid_sentence_start",
    "mid_word_end",
    "low_energy_tail",
    "flub_repeats",
    "peak_clipping",
)


def _signal_disabled_terms(*, transcript: bool, visual: bool) -> set[str]:
    disabled: set[str] = set()
    if not transcript:
        disabled |= set(TRANSCRIPT_DISABLED_TERMS)
    if not visual:
        disabled.add("visual_activity")
    # No face feature producer exists in the pipeline (SCORING_ENGINE §2.9).
    disabled.add("face_presence")
    return disabled


def _embedded_features(candidates_data: dict) -> list[CandidateFeatures]:
    """Reconstruct per-candidate inputs from an enriched document (re-score path)."""
    features: list[CandidateFeatures] = []
    for candidate in candidates_data.get("candidates", []):
        score = candidate.get("score")
        if not isinstance(score, dict):
            raise PipelineError(
                "candidates.json has no embedded ScoreBreakdown — scoring needs the "
                "sibling analysis.json on the first pass"
            )
        terms = {
            term["term"]: dict(term.get("inputs", {}))
            for term in score.get("terms", [])
            if isinstance(term, dict)
        }
        penalties = {
            penalty["rule"]: dict(penalty.get("inputs", {}))
            for penalty in score.get("penalties", [])
            if isinstance(penalty, dict)
        }
        features.append(
            CandidateFeatures(
                candidate_id=str(candidate.get("id", "")),
                start=float(candidate.get("start", 0.0)),
                end=float(candidate.get("end", 0.0)),
                duration=float(candidate.get("duration", 0.0)),
                terms=terms,
                penalties=penalties,
            )
        )
    return features


def score_candidates(
    candidates_data: dict,
    config: ScoriaConfig,
    analysis_data: dict | None = None,
) -> dict:
    """Build the enriched candidates document with one `ScoreBreakdown` per candidate.

    `analysis_data` is required only on the first pass against a raw (v1) document;
    re-scores read the embedded inputs and ignore it.
    """

    info = CandidatesInfo.model_validate(candidates_data)

    if analysis_data is not None:
        transcript_present = bool(
            analysis_data.get("transcript") is not None and analysis_data["transcript"].get("words")
        )
        visual_present = bool(
            analysis_data.get("visual") is not None
            and analysis_data["visual"].get("scenes") is not None
        )
        features = build_candidate_features(analysis_data, info, config)
    else:
        # Re-score: the enriched doc embeds *its own* signals_disabled — recomputing
        # presence from a missing analysis.json would silently drop transcript/visual
        # terms and renormalize the wrong weight set.
        signals_disabled = set(
            (candidates_data.get("scoring_meta") or {}).get("signals_disabled", [])
        )
        transcript_present = "transcript" not in signals_disabled
        visual_present = "visual" not in signals_disabled
        features = _embedded_features(candidates_data)

    disabled = _signal_disabled_terms(transcript=transcript_present, visual=visual_present)
    weights = config.scoring.renormalized_weights(disabled=disabled)

    raw_enabled = config.scoring.enabled_weights()
    renorm_factor = 1.0 / sum(raw_enabled[name] for name in weights) if weights else 0.0

    scoring_meta = ScoringMeta(
        scoring_version=config.scoring.version,
        signals_disabled=sorted(
            signal
            for signal, present in (("transcript", transcript_present), ("visual", visual_present))
            if not present
        ),
        renorm_factor=renorm_factor,
    )

    candidates_out: list[dict[str, Any]] = []
    for candidate, feat in zip(info.candidates, features, strict=True):
        term_scores = _score_terms(feat, weights, config)
        subscore_sum = sum(term.weighted for term in term_scores)

        penalties = _score_penalties(feat, config)
        penalty_total = min(sum(p.value for p in penalties), config.scoring.penalties.total_cap)

        total = 100.0 * max(0.0, min(1.0, subscore_sum - penalty_total))
        breakdown = ScoreBreakdown(
            total=total,
            subscore_sum=subscore_sum,
            penalty_total=penalty_total,
            renorm_factor=renorm_factor,
            terms=term_scores,
            penalties=penalties,
        )
        candidate_dump = candidate.model_dump(mode="json", by_alias=True)
        candidates_out.append(
            {**candidate_dump, "score": normalize(breakdown.model_dump(mode="json"))}
        )

    enriched = dict(candidates_data)
    enriched.update(
        {
            "version": SCORED_CANDIDATES_VERSION,
            "scoring_version": config.scoring.version,
            "scoring_meta": normalize(scoring_meta.model_dump(mode="json")),
            "candidates": candidates_out,
        }
    )
    return enriched


def _score_terms(
    feat: CandidateFeatures,
    weights: dict[str, float],
    config: ScoriaConfig,
) -> list[TermScore]:
    ordered = (name for name in _WEIGHT_FIELDS if name in weights)
    out: list[TermScore] = []
    for name in ordered:
        raw, normalized, note = TERM_FUNCS[name](feat.terms.get(name, {}), config)
        out.append(
            TermScore(
                term=name,
                function=FUNCTION_IDS[name],
                inputs=feat.terms.get(name, {}),
                raw=raw,
                normalized=normalized,
                weight=weights[name],
                weighted=weights[name] * normalized,
                note=note,
            )
        )
    return out


def _score_penalties(feat: CandidateFeatures, config: ScoriaConfig) -> list[PenaltyScore]:
    out: list[PenaltyScore] = []
    for rule in _PENALTY_ROW:
        if not getattr(config.scoring.penalties.config, rule):
            continue
        value = PENALTY_RULES[rule](feat.penalties.get(rule, {}), config)
        if value is None:
            continue
        out.append(
            PenaltyScore(
                rule=rule,
                function=PENALTY_FUNCTION_IDS[rule],
                inputs=feat.penalties.get(rule, {}),
                value=value,
                note=_penalty_note(rule),
            )
        )
    return out


def _penalty_note(rule: str) -> str:
    return {
        "leading_silence": "starts inside silence",
        "trailing_silence": "ends inside silence",
        "dead_air": "internal silence exceeds dead_air budget",
        "mid_sentence_start": "starts mid-sentence (gap > 300ms)",
        "mid_word_end": "ends inside a word span",
        "low_energy_tail": "last 1s RMS < 30% of clip mean",
        "flub_repeats": "adjacent repeats ≥ 0.5% of words",
        "peak_clipping": "clipped windows > 2%",
    }[rule]
