"""ScoreBreakdown + ranking-context renderers for `clipper explain` (Sprint 10).

`explain_one` joins the enriched candidates document (each candidate's embedded
`ScoreBreakdown`, Sprint 5) with ranking.json's decision log (Sprint 6) for one
clip id. Three renderers share one data shape: plain text (default, the debugging
surface), JSON (raw, for scripting — CLI_SPEC `--json`) and YAML. The embedded
breakdown is passed through untouched, so `explain --json` is byte-identical to
the candidate's `score` object.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import yaml

from scoria.errors import PipelineError

ExplainFormat = Literal["text", "json", "yaml"]


def _fmt(value: Any, digits: int = 4) -> str:
    return "-" if value is None else f"{float(value):.{digits}f}"


def explain_one(
    ranking: dict[str, Any], candidates: dict[str, Any], clip_id: str
) -> dict[str, Any]:
    """Join one clip's embedded breakdown with its ranking decision.

    Raises `PipelineError` when candidates is not an enriched candidates document
    or the clip id is unknown.
    """
    if not isinstance(candidates, dict) or candidates.get("schema") != "candidates":
        raise PipelineError(
            "not a candidates document (schema != 'candidates')",
            hint="run `clipper segment` + `clipper score` first, then `clipper explain`",
        )
    clip = next((c for c in candidates.get("candidates", []) if c.get("id") == clip_id), None)
    if clip is None:
        raise PipelineError(
            f"clip {clip_id!r} not in candidates",
            hint="clip ids are c0001-shaped; `clipper report` lists them with scores",
        )
    breakdown = clip.get("score")
    if not isinstance(breakdown, dict):
        raise PipelineError(
            f"clip {clip_id!r} has no embedded ScoreBreakdown",
            hint="run `clipper score <candidates.json>` to enrich the document",
        )
    return {
        "clip": clip_id,
        "start": clip.get("start"),
        "end": clip.get("end"),
        "duration": clip.get("duration"),
        "breakdown": breakdown,
        "ranking": _ranking_context(ranking, clip_id),
    }


def _ranking_context(ranking: dict[str, Any], clip_id: str) -> dict[str, Any]:
    for clip in ranking.get("selected", []) if isinstance(ranking, dict) else []:
        if clip.get("id") == clip_id:
            return {
                "status": "selected",
                "rank": clip.get("rank"),
                "gain": clip.get("gain"),
                "gain_note": clip.get("gain_note", ""),
                "step": _chosen_step(ranking, clip_id),
            }
    for clip in ranking.get("rejected", []) if isinstance(ranking, dict) else []:
        if clip.get("id") == clip_id:
            return {
                "status": "rejected",
                "best_gain": clip.get("best_gain"),
                "step": clip.get("step"),
                "reason": clip.get("reason", ""),
            }
    return {
        "status": "not_ranked",
        "note": f"{clip_id} appears in neither selected nor rejected of ranking.json",
    }


def _chosen_step(ranking: dict[str, Any], clip_id: str) -> int | None:
    for step in ranking.get("decisions", []):
        if step.get("selected") == clip_id:
            return step.get("step")
    return None


def render_explain_text(data: dict[str, Any]) -> str:
    """Human-readable breakdown table + ranking note (deterministic formatting)."""
    breakdown = data["breakdown"]
    lines = [
        f"clip {data['clip']}  "
        f"{_fmt(data.get('start'), 3)}s..{_fmt(data.get('end'), 3)}s  "
        f"({_fmt(data.get('duration'), 3)}s)"
    ]
    lines.append(
        f"  total {_fmt(breakdown.get('total'))} = "
        f"subscores {_fmt(breakdown.get('subscore_sum'))} - "
        f"penalties {_fmt(breakdown.get('penalty_total'))} "
        f"(renorm {_fmt(breakdown.get('renorm_factor'))})"
    )
    terms = breakdown.get("terms") or []
    if terms:
        lines.append("  terms:")
        for term in terms:
            lines.append(
                f"    {term['term']:<18} "
                f"weighted {_fmt(term.get('weighted')):>9}  "
                f"normalized {_fmt(term.get('normalized'))}  "
                f"raw {_fmt(term.get('raw')):>9}  "
                f"weight {_fmt(term.get('weight'))}  [{term.get('function')}]"
            )
            if term.get("note"):
                lines.append(f"      note: {term['note']}")
    penalties = breakdown.get("penalties") or []
    if penalties:
        lines.append("  penalties:")
        for penalty in penalties:
            lines.append(
                f"    {penalty['rule']:<18} "
                f"{_fmt(penalty.get('value')):>9}  [{penalty.get('function')}]"
            )
            if penalty.get("note"):
                lines.append(f"      note: {penalty['note']}")
    lines.append(f"  ranking: {_ranking_note(data.get('ranking') or {})}")
    return "\n".join(lines) + "\n"


def _ranking_note(context: dict[str, Any]) -> str:
    status = context.get("status")
    if status == "selected":
        return (
            f"selected rank #{context.get('rank')} at step {context.get('step')} "
            f"— gain {_fmt(context.get('gain'))} — {context.get('gain_note', '')}"
        )
    if status == "rejected":
        return (
            f"rejected — best_gain {_fmt(context.get('best_gain'))} "
            f"at step {context.get('step')} — {context.get('reason', '')}"
        )
    return f"not ranked ({context.get('note', '')})"


def render_explain_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, indent=2) + "\n"


def render_explain_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=True)


def render_explain(data: dict[str, Any], fmt: ExplainFormat = "text") -> str:
    if fmt == "json":
        return render_explain_json(data)
    if fmt == "yaml":
        return render_explain_yaml(data)
    return render_explain_text(data)
