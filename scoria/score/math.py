"""Pure curve helpers used by every sub-score (SCORING_ENGINE.md §2).

Both helpers are closed-form and deterministic: no RNG, no state, no I/O.
`smoothstep` is the x²(3−2x) Hermite step used by the monotone terms
(audio_energy, speech_density, keyword_density); `trapezoid` is the
flat-top "bell" used by the banded terms (pacing, sentence_quality).
"""

from __future__ import annotations


def smoothstep(x: float, low: float, high: float) -> float:
    """Normalized, clamped Hermite step: 0 below `low`, 1 above `high`.

    Returns 3t²−2t³ where t = clamp((x−low)/(high−low), 0, 1). `high` must
    exceed `low`; callers keep the config bounds valid (config load enforces
    the defaults, tests pin the guard).
    """
    if high <= low:
        raise ValueError(f"smoothstep bounds must satisfy low < high, got ({low}, {high})")
    t = (x - low) / (high - low)
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def trapezoid(x: float, a: float, b: float, c: float, d: float) -> float:
    """Flat-top trapezoid over four x-knots: 0 ≤ a, 0→1 in (a,b), 1 in [b,c],
    1→0 in (c,d), 0 ≥ d. Degenerate ramps (b ≤ a or c ≥ d) degrade to jumps."""
    if x <= a:
        return 0.0
    if x < b:
        return (x - a) / (b - a) if b > a else 1.0
    if x <= c:
        return 1.0
    if x < d:
        return (d - x) / (d - c) if d > c else 0.0
    return 0.0
