"""Deterministic audio feature math — pure numpy, zero I/O.

Windowed RMS/energy over pinned windows, silence detection with min-duration merge,
and peak statistics. No RNG: identical float arrays produce identical features
(ARCHITECTURE.md §5.1, §7). PCM f32 decoded samples are already in [-1, 1]; the
reductions below are the single source of the `audio` feature numbers.
"""

from __future__ import annotations

import numpy as np

from scoria.audio.models import PeakInfo, SilenceSpan

_EPS = 1e-12


def window_size(*, rate: int, window_ms: int) -> int:
    return max(1, round(rate * window_ms / 1000))


def window_count(samples: np.ndarray, *, rate: int, window_ms: int) -> int:
    """Number of full windows; the trailing partial window is dropped."""
    window = window_size(rate=rate, window_ms=window_ms)
    return samples.shape[0] // window


def slice_samples(samples: np.ndarray, *, rate: int, start: float, end: float) -> np.ndarray:
    """Return samples in [start, end) seconds.

    Windowed analysis slices the decoded array in numpy — never ffmpeg seeking — so
    a staged run is *exactly* a slice of a whole-file extraction (accepted criteria:
    staged vs whole-file equal).
    """
    s0 = max(0, round(start * rate))
    s1 = min(samples.shape[0], round(end * rate))
    return samples[s0:s1]


def windowed_features(
    samples: np.ndarray, *, rate: int, window_ms: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return (rms, energy) per window. energy = mean square; rms = sqrt(energy).

    Reduction is float64 over the exact windowed float32 payload (fixed order → the
    same array always produces the same floats).
    """
    window = window_size(rate=rate, window_ms=window_ms)
    count = samples.shape[0] // window
    if count == 0:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)
    frame = samples[: count * window].reshape(count, window).astype(np.float64)
    energy = np.mean(frame * frame, axis=1)
    return np.sqrt(energy), energy


def silence_db(rms: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.asarray(rms, dtype=np.float64) + _EPS)


def detect_silence(
    rms: np.ndarray,
    *,
    window_seconds: float,
    threshold_db: float,
    min_duration: float,
    offset_seconds: float = 0.0,
) -> list[SilenceSpan]:
    """Silent windows (rms < threshold) → contiguous runs, merged when the gap
    between runs is < `min_duration`, emitted only when the run is ≥ `min_duration`.

    Window i covers [i·w, (i+1)·w) analyzed seconds; span times are absolute
    (`offset_seconds` added).
    """
    if min_duration <= 0.0 or window_seconds <= 0.0:
        return []
    silent = silence_db(rms) < threshold_db
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_silent in enumerate(silent):
        if is_silent and start is None:
            start = index
        elif not is_silent and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(silent) - 1))
    merged: list[tuple[int, int]] = []
    for first, last in runs:
        gap = (first - (merged[-1][1] + 1) if merged else 0) * window_seconds
        if merged and gap < min_duration:
            merged[-1] = (merged[-1][0], last)
        else:
            merged.append((first, last))
    spans: list[SilenceSpan] = []
    for first, last in merged:
        start = first * window_seconds + offset_seconds
        end = (last + 1) * window_seconds + offset_seconds
        if end - start >= min_duration:
            spans.append(SilenceSpan(start=start, end=end, duration=end - start))
    return spans


def peak_stats(samples: np.ndarray, *, threshold: float) -> PeakInfo:
    """Peak statistics: max abs sample + fraction of samples at or above `threshold`
    (near full scale → clipping/very-hot content, the mild quality guard)."""
    clipped = np.abs(samples) >= threshold
    count = clipped.shape[0]
    return PeakInfo(
        max_abs=float(np.abs(samples).max()) if count else 0.0,
        clip_fraction=float(np.mean(clipped)) if count else 0.0,
        clip_count=int(clipped.sum()),
        sample_count=int(count),
    )
