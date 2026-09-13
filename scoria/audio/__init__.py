"""Audio analysis: PCM extraction, windowed RMS/energy, silence, loudness, peaks (Sprint 2).

`analysis.json.audio` is the deterministic feature archive consumed by scoring
(audio_energy, hook bursts, pacing) and segmentation (silence boundaries, dead-air
and edge-silence penalties).
"""

from scoria.audio.core import detect_silence, peak_stats, slice_samples, windowed_features
from scoria.audio.extract import extract_pcm, measure_loudness
from scoria.audio.models import (
    AUDIO_SCHEMA,
    AudioInfo,
    LoudnessInfo,
    PeakInfo,
    SilenceSpan,
)
from scoria.audio.pipeline import analyze_audio

__all__ = [
    "AUDIO_SCHEMA",
    "AudioInfo",
    "LoudnessInfo",
    "PeakInfo",
    "SilenceSpan",
    "analyze_audio",
    "detect_silence",
    "extract_pcm",
    "measure_loudness",
    "peak_stats",
    "slice_samples",
    "windowed_features",
]
