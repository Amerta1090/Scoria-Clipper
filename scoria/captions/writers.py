"""SRT + ASS writers. Pure string builders — no I/O — so golden strings can be
pinned byte-for-byte and parse-back checks stay offline (Sprint 7 tests).

Deterministic: fixed number formats (round-half-even via Python's `round`),
stable ordering (block order from the line builder), no locale dependence.
"""

from __future__ import annotations

from scoria.captions.models import Caption
from scoria.config.schema import AssStyleConfig

# ---------------------------------------------------------------------------
# timestamp formats
# ---------------------------------------------------------------------------


def format_srt_timestamp(seconds: float) -> str:
    """00:00:01,500 — zero-padded HH:MM:SS,mmm (SRT spec)."""
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_ass_timestamp(seconds: float) -> str:
    """0:00:01.50 — H:MM:SS.cc with un-padded hours (ASS spec)."""
    centis = round(seconds * 100)
    hours, rem = divmod(centis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------


def write_srt(captions: list[Caption]) -> str:
    """SRT text: numbered cues, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, blank-line separated."""
    out: list[str] = []
    for index, caption in enumerate(captions, start=1):
        out.append(f"{index}\n")
        out.append(
            f"{format_srt_timestamp(caption.start)} --> {format_srt_timestamp(caption.end)}\n"
        )
        out.append("\n".join(caption.lines))
        out.append("\n\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# ASS
# ---------------------------------------------------------------------------


def _dialogue_text(caption: Caption, karaoke: bool) -> str:
    if not karaoke:
        return "\\N".join(caption.lines)
    return " ".join(
        f"{{\\k{round((word.end - word.start) * 100)}}}{word.text}" for word in caption.words
    )


def _write_ass_header(style: AssStyleConfig, play_res: tuple[int, int]) -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res[0]}\n"
        f"PlayResY: {play_res[1]}\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {style.name},{style.font},{style.font_size},{style.primary_colour},"
        f"&H0000FFFF,{style.outline_colour},&H80000000,0,0,0,0,100,100,0,0,1,"
        f"{style.outline},{style.shadow},2,10,10,{style.margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def write_ass(
    captions: list[Caption],
    style: AssStyleConfig,
    play_res: tuple[int, int] = (1080, 1920),
) -> str:
    """ASS text: [Script Info] + [V4+ Styles] from `style`, `{\\k..}` word-karaoke."""
    header = _write_ass_header(style, play_res)
    if not captions:
        return header
    parts = [header.rstrip("\n")]
    for caption in captions:
        parts.append(
            f"Dialogue: 0,{format_ass_timestamp(caption.start)},"
            f"{format_ass_timestamp(caption.end)},{style.name},,0,0,0,,"
            f"{_dialogue_text(caption, style.karaoke_words)}"
        )
    return "\n".join(parts) + "\n"
