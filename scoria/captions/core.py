"""Orchestrator: ranking.json + analysis.json + config → captions.json doc.

Pure: no I/O here (the CLI reads the JSON artifacts and writes the sidecars).
Word timestamps come from the analysis transcript (`transcript-info` schema,
ADR-013 word timestamps); `build_captions` is deterministic — same ranking +
analysis + config → same document (SCORING-independent Sprint 7 entry point).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scoria.captions.lines import build_clip_captions
from scoria.captions.models import (
    CAPTION_VERSION,
    CAPTIONS_SCHEMA,
    CAPTIONS_VERSION,
    CaptionsInfo,
    ClipCaptions,
)
from scoria.captions.writers import write_ass, write_srt
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


def write_caption_sidecars(doc: CaptionsInfo, out_dir, cfg) -> list[Path]:
    """Write the id-keyed `captions/<clip_id>.srt|.ass` sidecars.

    Shared by the `captions` and `render` (Sprint 9) CLIs so burn-in always
    consumes exactly the same files the user sees. Config-format driven
    (`cfg.captions.format`); returns the created paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for clip in doc.clips:
        if not clip.captions:
            continue
        if "srt" in cfg.captions.format:
            path = out_dir / f"{clip.id}.srt"
            path.write_text(write_srt(clip.captions), encoding="utf-8")
            files.append(path)
        if "ass" in cfg.captions.format:
            path = out_dir / f"{clip.id}.ass"
            path.write_text(write_ass(clip.captions, cfg.captions.ass_style), encoding="utf-8")
            files.append(path)
    return files


__all__ = [
    "CAPTIONS_SCHEMA",
    "CAPTIONS_VERSION",
    "CAPTION_VERSION",
    "build_captions",
    "write_caption_sidecars",
]
