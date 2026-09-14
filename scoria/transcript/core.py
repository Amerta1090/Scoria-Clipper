"""Pure sentence-grouping + word-normalization rules (ARCHITECTURE.md §5.3, ADR-013).

Everything here is deterministic and testable without any STT tool: it consumes the
parsed word list (flat, whisper segment order) and produces ordered sentences.
"""

from __future__ import annotations

from collections.abc import Sequence

from scoria.transcript.models import Sentence, Word

# A whisper segment end only breaks a sentence when the inter-word pause is at least
# this long; anything shorter is the "mid-sentence trap" (whisper splits segments on
# short breaths, not sentences). Config's `max_gap_seconds` still governs the real pauses.
SEGMENT_BREAK_MIN_GAP_S = 0.30

# First-word openers that make a sentence a question (en + id, lowercased).
DEFAULT_QUESTION_STARTERS: frozenset[str] = frozenset(
    {
        "who",
        "whose",
        "whom",
        "what",
        "which",
        "when",
        "where",
        "why",
        "how",
        "can",
        "could",
        "do",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
        "should",
        "would",
        "apa",
        "apakah",
        "bagaimana",
        "berapa",
        "kapan",
        "kenapa",
        "mengapa",
        "siapa",
    }
)

_TERMINAL_PUNCTUATION = (".", "?", "!")


def normalize_words(words: Sequence[Word]) -> list[Word]:
    """Strip whitespace, drop empty words, and make the timeline strictly monotonic.

    Whisper token `t_dtw` values occasionally overlap at tiny gaps; the snap rule
    (`start = max(start, prev_end)`, `end = max(end, start)`) guarantees the
    "no word overlap" acceptance criterion regardless of model jitter.
    """
    out: list[Word] = []
    cursor = 0.0
    for word in words:
        text = word.text.strip()
        if not text:
            continue
        start = max(word.start, cursor)
        end = max(word.end, start)
        cursor = end
        out.append(Word(text=text, start=start, end=end))
    return out


def _punctuate(text: str, question_starters: frozenset[str]) -> str:
    first = text.split(" ", 1)[0].lower() if text else ""
    mark = "?" if first in question_starters else "."
    return f"{text}{mark}"


def group_sentences(
    words: Sequence[Word],
    *,
    max_gap_seconds: float,
    min_sentence_words: int,
    force_punctuation: bool,
    segment_end_indices: Sequence[int] = (),
    question_starters: frozenset[str] = DEFAULT_QUESTION_STARTERS,
) -> list[Sentence]:
    """Group normalized words into sentences.

    A split lands before word `i+1` when the pause after word `i` is >=
    `max_gap_seconds`, or `i` is a whisper segment end and the pause is >=
    `SEGMENT_BREAK_MIN_GAP_S` (keeps short segment-boundary breaths mid-sentence
    merged). Sentences shorter than `min_sentence_words` absorb into the previous
    one. `force_punctuation` infers `?`/`.` from the first word.
    """
    if not words:
        return []
    segment_ends = set(segment_end_indices)
    starts = [0]
    for i in range(len(words) - 1):
        pause = words[i + 1].start - words[i].end
        if pause >= max_gap_seconds or (i in segment_ends and pause >= SEGMENT_BREAK_MIN_GAP_S):
            starts.append(i + 1)
    boundaries = [*starts, len(words)]

    spans = [(boundaries[k], boundaries[k + 1]) for k in range(len(boundaries) - 1)]
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and (end - start) < min_sentence_words:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    sentences: list[Sentence] = []
    for start, end in merged:
        part = words[start:end]
        text = " ".join(word.text for word in part)
        if force_punctuation and text and not text.endswith(_TERMINAL_PUNCTUATION):
            text = _punctuate(text, question_starters)
        if not text:
            continue
        sentences.append(
            Sentence(
                text=text[:1].upper() + text[1:],
                start=part[0].start,
                end=part[-1].end,
                words=list(part),
            )
        )
    return sentences
