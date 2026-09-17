"""Captions: word timestamps → readable SRT/ASS sidecars (Sprint 7).

`build_captions` is the entry point: selected clips (ranking.json) + transcript
words (analysis.json) + captions config → the captions.json document. The CLI
writes that document plus the per-clip `captions/<clip_id>.srt` / `.ass`
sidecars (word-karaoke `\\k` when `ass_style.karaoke_words`). Line building,
timing and wrapping live in `lines.py`; string writers are pure in `writers.py`.
"""

from scoria.captions.core import (
    CAPTION_VERSION,
    CAPTIONS_SCHEMA,
    CAPTIONS_VERSION,
    build_captions,
    write_caption_sidecars,
)
from scoria.captions.lines import build_clip_captions, clamp_words
from scoria.captions.models import Caption, CaptionsInfo, ClipCaptions
from scoria.captions.writers import format_ass_timestamp, format_srt_timestamp, write_ass, write_srt

__all__ = [
    "CAPTION_VERSION",
    "CAPTIONS_SCHEMA",
    "CAPTIONS_VERSION",
    "Caption",
    "CaptionsInfo",
    "ClipCaptions",
    "build_captions",
    "build_clip_captions",
    "clamp_words",
    "format_ass_timestamp",
    "format_srt_timestamp",
    "write_ass",
    "write_caption_sidecars",
    "write_srt",
]
