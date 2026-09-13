"""Typed audio-analysis output: the `audio` section of analysis.json.

Canonical feature archive for scoring/render (ARCHITECTURE.md §5.1): per-window
RMS + energy series (50 ms windows), silence spans, ebur128 loudness, peaks.
Timestamps are absolute seconds aligned to the analysis window (`media.analysis`) —
silence `start`/`end` already include the `analyze_start` offset. Floats are rounded
to 4 decimals by the serialization contract on write.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AUDIO_SCHEMA = "audio-info"


class SilenceSpan(BaseModel):
    start: float
    end: float
    duration: float


class LoudnessInfo(BaseModel):
    integrated_lufs: float | None
    true_peak_db: float | None


class PeakInfo(BaseModel):
    max_abs: float
    clip_fraction: float
    clip_count: int
    sample_count: int


class AudioInfo(BaseModel):
    """`rms` is the canonical series for scoring (audio_energy uses RMS/R95);
    `energy` = mean square per window (rms²) is kept for hook-burst math."""

    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["audio-info"] = Field(AUDIO_SCHEMA, alias="schema")
    sample_rate: int
    window_ms: int
    window_samples: int
    window_seconds: float
    windows: int
    offset_seconds: float
    analyzed_seconds: float
    rms: list[float]
    energy: list[float]
    rms_p95: float
    energy_p95: float
    silence_threshold_db: float
    silence: list[SilenceSpan]
    loudness: LoudnessInfo
    peaks: PeakInfo
