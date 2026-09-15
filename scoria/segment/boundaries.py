"""Boundary list construction: the sorted, deduplicated union of silence spans,
sentence starts/ends, and scene changes (ARCHITECTURE.md §5.4).

Signals that land within `BOUNDARY_DEDUPE_S` (50 ms) of each other collapse into
a single boundary carrying the union of their source labels; label order follows
`BOUNDARY_SOURCE_ORDER`. The output is deterministic and sorted by time.
"""

from __future__ import annotations

from scoria.segment.models import BOUNDARY_SOURCE_ORDER, Boundary

BOUNDARY_DEDUPE_S = 0.05


def _normalized_sources(sources: set[str]) -> list[str]:
    known = [label for label in BOUNDARY_SOURCE_ORDER if label in sources]
    unknown = sorted(sources - set(BOUNDARY_SOURCE_ORDER))
    return list(known) + unknown


def build_boundaries(
    *,
    silence: list[tuple[float, float]] | None = None,
    sentences: list[tuple[float, float]] | None = None,
    scenes: list[tuple[float, float]] | None = None,
    dedupe_s: float = BOUNDARY_DEDUPE_S,
) -> list[Boundary]:
    """Build boundaries from signal lists of (start, end) / (time) pairs.

    Accepts bare tuples so unit tests can call it without pydantic models;
    `scenes` entries are single (time,) times represented as (time, time).
    """
    entries: list[tuple[float, str]] = []
    for start, end in silence or ():
        entries.append((start, "silence_start"))
        entries.append((end, "silence_end"))
    for start, end in sentences or ():
        entries.append((start, "sentence_start"))
        entries.append((end, "sentence_end"))
    for time, _ in scenes or ():
        entries.append((time, "scene"))

    entries.sort(key=lambda item: (item[0], item[1]))

    boundaries: list[Boundary] = []
    for time, source in entries:
        if boundaries and time - boundaries[-1].time <= dedupe_s:
            sources = set(boundaries[-1].sources)
            sources.add(source)
            boundaries[-1].sources = _normalized_sources(sources)
        else:
            boundaries.append(Boundary(time=time, sources=_normalized_sources({source})))
    return boundaries
