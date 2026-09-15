"""Window generator: raw candidate windows from the boundary list.

Implements ARCHITECTURE.md §5.4. For each start boundary (skipping starts whose
min reachable duration is below `min_duration`) it emits at most
`max_candidates_per_start` windows:

- **A (preferred):** the boundary nearest the preferred band `[s+pref_min, s+pref_max]`
  (tie → the earlier time).
- **B (max extension):** the last boundary at or before `s+max_duration`. Falls
  back to the nearest boundary in a `hard_cut_margin` grace band just past max so
  a cut can land on a real boundary instead of inside a long sentence.
- **Hard cut:** when no boundary is reachable and no grace boundary exists, cut
  exactly at `min(s+max_duration, media_end)` and flag `hard_cut`.

Starts too close to the window end — `min(s+max, media_end) - s < min_duration` —
produce nothing. Output is deterministic.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from scoria.segment.models import Boundary


@dataclass(frozen=True)
class StartBoundary:
    time: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class WindowSpec:
    start: float
    end: float
    start_sources: tuple[str, ...]
    end_sources: tuple[str, ...]
    hard_cut: bool


def _has_sentence(sources: tuple[str, ...]) -> bool:
    return any(source.startswith("sentence") for source in sources)


def generate_candidates(
    boundaries: list[Boundary],
    *,
    media_start: float,
    media_end: float,
    min_duration: float,
    pref_min: float,
    pref_max: float,
    max_duration: float,
    max_candidates_per_start: int,
    hard_cut_margin: float = 0.25,
) -> list[WindowSpec]:
    times = [boundary.time for boundary in boundaries]
    pref_center = (pref_min + pref_max) / 2.0

    windows: list[WindowSpec] = []
    for start_data in boundaries:
        start = start_data.time
        if start < media_start:
            continue
        if start >= media_end:
            break
        upper = min(start + max_duration, media_end)
        if upper - start < min_duration:
            continue

        lo = bisect_right(times, start)
        hi = bisect_right(times, upper)
        reachable = boundaries[lo:hi]

        p_lo = bisect_left(times, start + pref_min)
        p_hi = bisect_right(times, min(start + pref_max, upper))
        pref_ends = boundaries[p_lo:p_hi]

        pref: Boundary | None = None
        if pref_ends:
            pref = min(pref_ends, key=lambda b: (abs(b.time - (start + pref_center)), b.time))

        ext: Boundary | None = reachable[-1] if reachable else None
        if ext is None and upper < media_end:
            m_lo = bisect_right(times, upper)
            m_hi = bisect_right(times, upper + hard_cut_margin)
            if m_hi > m_lo:
                ext = boundaries[m_hi - 1]

        candidates: list[WindowSpec] = []
        if pref is not None:
            candidates.append(
                WindowSpec(
                    start=start,
                    end=pref.time,
                    start_sources=start_data.sources,
                    end_sources=pref.sources,
                    hard_cut=False,
                )
            )
        if ext is not None:
            if pref is None or ext.time != pref.time:
                if ext.time - start >= min_duration:
                    candidates.append(
                        WindowSpec(
                            start=start,
                            end=ext.time,
                            start_sources=start_data.sources,
                            end_sources=ext.sources,
                            hard_cut=False,
                        )
                    )
        if not candidates:
            candidates.append(
                WindowSpec(
                    start=start,
                    end=upper,
                    start_sources=start_data.sources,
                    end_sources=(),
                    hard_cut=True,
                )
            )

        windows.extend(candidates[:max_candidates_per_start])

    seen: set[tuple[float, float]] = set()
    unique: list[WindowSpec] = []
    for window in windows:
        key = (window.start, window.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(window)
    return unique
