"""Line builder: transcript words → caption blocks within a clip window.

Pipeline (all pure + deterministic — same words + config → same blocks):

1. *Clamp* — keep only words that overlap the clip window and clip boundary
   words to the window (a word overlapping the cut is shown only for its
   on-screen part; zero/negative spans are dropped).
2. *Chunk by duration* — greedy over transcript order: a chunk's span
   (last word end − first word start) never exceeds `max_duration`.
3. *Wrap* — each chunk's words become ≤ `max_lines` lines, every line
   ≤ `chars_per_line` chars. With `prefer_sentence_breaks`, a line break is
   reflowed to the *last sentence end already inside the line* instead of
   cutting mid-sentence; a word longer than a full line stays whole.
4. *Filter* — blocks with fewer than `min_word_count` words are dropped
   (default 1 drops nothing).

A single word longer than `chars_per_line` occupies its own full line, and a
single word longer than `max_duration` cannot be split — both stay whole
(correctness over style, documented ADR-018).

Sentence-boundary heuristic: a word ends a sentence when its text ends with
`. ! ? …` optionally followed by closing quotes/brackets. Used only to pick
reflow points — never changes timing or word order.
"""

from __future__ import annotations

import re

from scoria.captions.models import Caption
from scoria.config.schema import CaptionsConfig
from scoria.transcript.models import Word

_SENTENCE_END = re.compile(r'[.!?…]["\'”»)\]]*$')


def clamp_words(words: list[Word], start: float, end: float) -> list[Word]:
    """Filter transcript words to the [start, end) window, clipping boundary words."""
    out: list[Word] = []
    for word in words:
        clipped_start = max(word.start, start)
        clipped_end = min(word.end, end)
        if clipped_start < clipped_end:
            out.append(Word(text=word.text, start=clipped_start, end=clipped_end))
    return out


def chunk_by_duration(words: list[Word], max_duration: float) -> list[list[Word]]:
    """Greedy chunks whose span (last.end − first.start) ≤ max_duration."""
    chunks: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current and word.end - current[0].start > max_duration:
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def _line_chars(line: list[Word]) -> int:
    """Text length with single spaces between words."""
    return sum(len(word.text) for word in line) + (len(line) - 1)


def _line_text(line: list[Word]) -> str:
    return " ".join(word.text for word in line)


def wrap_words(
    words: list[Word],
    chars_per_line: int,
    max_lines: int,
    prefer_sentence_breaks: bool,
) -> list[list[list[Word]]]:
    """Wrap a duration-chunk into blocks of ≤ max_lines lines, lines ≤ chars_per_line.

    Returns blocks; each block is a list of lines; each line is a list of words.
    A line never exceeds `chars_per_line` (words are never split, so a single
    word longer than the limit occupies its own line).
    """
    blocks: list[list[list[Word]]] = []
    lines: list[list[Word]] = []
    line: list[Word] = []
    chars = 0

    def push_line() -> None:
        nonlocal lines, line, chars
        lines.append(line)
        line, chars = [], 0
        if len(lines) >= max_lines:
            blocks.append(lines)
            lines = []

    def _last_sentence_end_index(candidate: list[Word]) -> int | None:
        """Last index < last whose text ends a sentence (a reflow point)."""
        for index in range(len(candidate) - 1, 0, -1):
            if _SENTENCE_END.search(candidate[index - 1].text):
                return index
        return None

    for word in words:
        if line and chars + 1 + len(word.text) > chars_per_line:
            tail: list[Word] = []
            if prefer_sentence_breaks:
                split_at = _last_sentence_end_index(line)
                if split_at is not None:
                    tail, line = line[split_at:], line[:split_at]
                    chars = _line_chars(line)
            push_line()
            if tail:
                line, chars = list(tail), _line_chars(tail)
        if line:
            chars += 1 + len(word.text)
        else:
            chars += len(word.text)
        line.append(word)
    if line:
        push_line()
    if lines:
        blocks.append(lines)
    return blocks


def build_clip_captions(
    words: list[Word], start: float, end: float, cfg: CaptionsConfig
) -> list[Caption]:
    """Build caption blocks for one clip window (pure, deterministic)."""
    window = clamp_words(words, start, end)
    blocks: list[Caption] = []
    for chunk in chunk_by_duration(window, cfg.max_duration):
        for block in wrap_words(
            chunk, cfg.chars_per_line, cfg.max_lines, cfg.prefer_sentence_breaks
        ):
            block_words = [word for line in block for word in line]
            if len(block_words) < cfg.min_word_count:
                continue
            blocks.append(
                Caption(
                    start=block_words[0].start,
                    end=block_words[-1].end,
                    lines=[_line_text(line) for line in block],
                    words=block_words,
                )
            )
    return blocks
