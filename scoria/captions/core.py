"""Orchestrator: ranking.json + analysis.json + config → captions.json doc.

Pure: no I/O here (the CLI reads the JSON artifacts and writes the sidecars).
Word timestamps come from the analysis transcript (`transcript-info` schema,
ADR-013 word timestamps); `build_captions` is deterministic — same ranking +
analysis + config → same document (SCORING-independent Sprint 7 entry point).
"""

from __future__ import annotations

from typing import Any

from scoria.captions.lines import build_clip_captions
from scoria.captions.models import (
    CAPTION_VERSION,
    CAPTIONS_SCHEMA,
    CAPTIONS_VERSION,
    CaptionsInfo,
    ClipCaptions,
)
from scoria.config.schema import ScoriaConfig
from scoria.transcript.models import Word


def build_captions(
    ranking: dict[str, Any], analysis: dict[str, Any], cfg: ScoriaConfig
) -> CaptionsInfo:
    """Selected clips (ranking.json) + transcript words (analysis.json) → blocks."""
    transcript = analysis.get("transcript") or {}
    words = [Word(**word) for word in transcript.get("words", [])]
    captions_cfg = cfg.captions
    clips: list[ClipCaptions] = []
    for selected in ranking.get("selected", []):
        start = float(selected["start"])
        end = float(selected["end"])
        clips.append(
            ClipCaptions(
                id=selected["id"],
                rank=int(selected["rank"]),
                start=start,
                end=end,
                captions=build_clip_captions(words, start, end, captions_cfg),
            )
        )
    return CaptionsInfo(
        version=CAPTIONS_VERSION,
        caption_version=CAPTION_VERSION,
        max_duration=captions_cfg.max_duration,
        chars_per_line=captions_cfg.chars_per_line,
        max_lines=captions_cfg.max_lines,
        min_word_count=captions_cfg.min_word_count,
        clips=clips,
    )


__all__ = ["CAPTIONS_SCHEMA", "CAPTIONS_VERSION", "CAPTION_VERSION", "build_captions"]
