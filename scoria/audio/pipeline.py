"""The audio stage: input file → `analysis.json.audio` (ARCHITECTURE.md §5.1).

Decode once to f32le mono PCM at the pinned rate, slice to the analysis window
(in numpy — identical to slicing a whole-file extraction), then reduce to the
feature contract consumed by scoring (audio_energy/hook/pacing) and segmentation
(silence boundaries, dead-air penalties). Zero RNG; fixed windows.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from scoria.audio.core import (
    detect_silence,
    peak_stats,
    slice_samples,
    window_size,
    windowed_features,
)
from scoria.audio.extract import extract_pcm, measure_loudness
from scoria.audio.models import AudioInfo
from scoria.config.schema import ScoriaConfig
from scoria.errors import MediaError
from scoria.util.logging import get_logger

if TYPE_CHECKING:
    from scoria.ingest.models import MediaInfo

logger = get_logger("audio")


def analyze_audio(input_path: Path, config: ScoriaConfig, media: MediaInfo) -> AudioInfo:
    """Extract + reduce audio for `media.analysis` and return the `audio` contract."""
    rate = config.media.analyze_audio_rate
    start = media.analysis.start
    end = media.analysis.end
    samples = extract_pcm(input_path, rate=rate)
    samples = slice_samples(samples, rate=rate, start=start, end=end)
    if samples.shape[0] == 0:
        raise MediaError(
            f"no audio samples in the analysis window [{start:g}s, {end:g}s)",
            hint="check audio.analyze_start/analyze_end against the input duration",
        )
    rms, energy = windowed_features(samples, rate=rate, window_ms=config.audio.window_ms)
    window_seconds = config.audio.window_ms / 1000
    if rms.shape[0] == 0:
        logger.warning(
            "analysis window shorter than one audio window (%g s); emitting empty audio",
            window_seconds,
            extra={"stage": "audio"},
        )
    windows = int(rms.shape[0])
    silence = detect_silence(
        rms,
        window_seconds=window_seconds,
        threshold_db=config.audio.silence.threshold_db,
        min_duration=config.audio.silence.min_duration,
        offset_seconds=start,
    )
    peaks = peak_stats(samples, threshold=config.audio.peak_threshold)
    loudness = measure_loudness(input_path, rate=rate)
    return AudioInfo(
        schema="audio-info",
        sample_rate=rate,
        window_ms=config.audio.window_ms,
        window_samples=window_size(rate=rate, window_ms=config.audio.window_ms),
        window_seconds=window_seconds,
        windows=windows,
        offset_seconds=start,
        analyzed_seconds=windows * window_seconds,
        rms=[float(value) for value in rms],
        energy=[float(value) for value in energy],
        rms_p95=float(np.quantile(rms, 0.95)) if windows else 0.0,
        energy_p95=float(np.quantile(energy, 0.95)) if windows else 0.0,
        silence_threshold_db=config.audio.silence.threshold_db,
        silence=silence,
        loudness=loudness,
        peaks=peaks,
    )
