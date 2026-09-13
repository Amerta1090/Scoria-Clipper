"""L0/L1: audio — windowed RMS/energy, silence detection, peaks, loudness, analysis.json.audio.

L0 = pure numpy feature math (no ffmpeg). L1 = PCM extraction + loudness + the
`analyze_audio` stage on tiny generated media with planted silence placement
(TESTING.md §2 — deterministic by construction, no network).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scoria.audio import (
    analyze_audio,
    detect_silence,
    extract_pcm,
    measure_loudness,
    peak_stats,
    slice_samples,
    windowed_features,
)
from scoria.config import build_config
from scoria.errors import MediaError
from scoria.ingest import analyze_video, build_media
from scoria.project import check_contract, dump_str

RATE = 16000
WINDOW_MS = 50
WINDOW_S = WINDOW_MS / 1000


def _tone(duration: float, amp: float = 0.5, freq: float = 440.0) -> np.ndarray:
    n = round(duration * RATE)
    t = np.arange(n) / RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _cfg(**overrides):
    data = {"media": {"min_duration": 1.0}}
    data.update(overrides)
    return build_config(overrides=data)


# ---------------------------------------------------------------------------
# L0: slicing + window math (pure)
# ---------------------------------------------------------------------------


def test_slice_samples_whole_equals_windowed():
    whole = _tone(2.0)
    sliced = slice_samples(whole, rate=RATE, start=0.0, end=1.0)
    assert sliced.shape[0] == RATE
    assert np.array_equal(sliced, whole[:RATE])


def test_windowed_features_sine():
    rms, energy = windowed_features(_tone(1.0, amp=0.5), rate=RATE, window_ms=WINDOW_MS)
    assert rms.shape == (20,)
    assert energy.shape == (20,)
    expected = 0.5 / np.sqrt(2)
    assert rms == pytest.approx(expected, rel=0.02)
    assert energy == pytest.approx(expected**2, rel=0.02)


def test_windowed_features_energy_monotonic():
    seg = _tone(0.25, amp=0.2)
    amps = np.linspace(0.1, 0.9, 12)
    samples = np.concatenate([(amp / 0.9 * seg).astype(np.float32) for amp in amps])
    rms, energy = windowed_features(samples, rate=RATE, window_ms=WINDOW_MS)
    assert rms.shape == (60,)
    assert np.all(np.diff(energy) >= 0)
    per_segment = energy.reshape(12, 5).mean(axis=1)
    assert np.all(np.diff(per_segment) > 0)


def test_energy_equals_rms_squared():
    rms, energy = windowed_features(_tone(1.0, amp=0.3), rate=RATE, window_ms=WINDOW_MS)
    assert np.allclose(energy, rms**2, rtol=1e-12)


def test_windowed_features_drops_partial_tail():
    samples = np.zeros(RATE + 100, dtype=np.float32)  # 1s + partial window
    rms, _ = windowed_features(samples, rate=RATE, window_ms=WINDOW_MS)
    assert rms.shape == (20,)


# ---------------------------------------------------------------------------
# L0: silence detection (pure)
# ---------------------------------------------------------------------------


def test_detect_silence_exact_spans():
    rms = np.concatenate([np.zeros(10), np.full(10, 0.2), np.zeros(10)])
    spans = detect_silence(rms, window_seconds=WINDOW_S, threshold_db=-35, min_duration=0.35)
    assert [(s.start, s.end) for s in spans] == [(0.0, 0.5), (1.0, 1.5)]
    assert [s.duration for s in spans] == pytest.approx([0.5, 0.5])


def test_detect_silence_merges_small_gap():
    # 0.1s loud blip inside a long silence folds in (gap < min_duration)
    rms = np.concatenate([np.zeros(8), np.full(2, 0.2), np.zeros(8)])
    spans = detect_silence(rms, window_seconds=WINDOW_S, threshold_db=-35, min_duration=0.35)
    assert [(s.start, s.end) for s in spans] == [(0.0, 0.9)]


def test_detect_silence_filters_short_runs():
    rms = np.concatenate([np.zeros(6), np.full(10, 0.2)])
    assert detect_silence(rms, window_seconds=WINDOW_S, threshold_db=-35, min_duration=0.35) == []
    spans = detect_silence(rms, window_seconds=WINDOW_S, threshold_db=-35, min_duration=0.2)
    assert len(spans) == 1
    assert spans[0].start == pytest.approx(0.0)
    assert spans[0].end == pytest.approx(0.3)


def test_detect_silence_offset_applied():
    rms = np.concatenate([np.zeros(10), np.full(10, 0.2)])
    spans = detect_silence(
        rms,
        window_seconds=WINDOW_S,
        threshold_db=-35,
        min_duration=0.35,
        offset_seconds=2.0,
    )
    assert [(s.start, s.end) for s in spans] == [(2.0, 2.5)]


def test_detect_silence_noise_floor():
    # near-silent non-zero content (AAC-decoded zeros are tiny but not exact)
    rms = np.concatenate([np.full(10, 1e-6), np.full(10, 0.2)])
    spans = detect_silence(rms, window_seconds=WINDOW_S, threshold_db=-35, min_duration=0.35)
    assert [(s.start, s.end) for s in spans] == [(0.0, 0.5)]


# ---------------------------------------------------------------------------
# L0: peaks (pure)
# ---------------------------------------------------------------------------


def test_peak_stats():
    samples = np.array([0.0, 0.5, -1.0, 1.0, 0.9], dtype=np.float32)
    peaks = peak_stats(samples, threshold=0.999)
    assert peaks.max_abs == 1.0
    assert peaks.clip_count == 2
    assert peaks.clip_fraction == pytest.approx(0.4)
    assert peaks.sample_count == 5


# ---------------------------------------------------------------------------
# L1: extraction + loudness on generated media
# ---------------------------------------------------------------------------


def test_extract_pcm_from_wav(planted_wav):
    samples = extract_pcm(planted_wav, rate=RATE)
    assert samples.dtype == np.float32
    assert samples.shape[0] == round(4.0 * RATE)
    assert float(samples.min()) >= -1.0
    assert float(samples.max()) <= 1.0


def test_audio_silence_spans_match_planted(planted_wav):
    cfg = _cfg()
    samples = extract_pcm(planted_wav, rate=RATE)
    rms, _ = windowed_features(samples, rate=RATE, window_ms=WINDOW_MS)
    spans = detect_silence(
        rms,
        window_seconds=WINDOW_S,
        threshold_db=cfg.audio.silence.threshold_db,
        min_duration=cfg.audio.silence.min_duration,
    )
    assert [(round(s.start, 2), round(s.end, 2)) for s in spans] == [(0.0, 0.5), (2.0, 4.0)]


def test_loudness_measured(planted_wav):
    loudness = measure_loudness(planted_wav, rate=RATE)
    assert loudness.integrated_lufs is not None
    assert -50.0 < loudness.integrated_lufs < -1.0


def test_no_audio_stream_is_actionable(video_only):
    cfg = _cfg()
    media = build_media(video_only, cfg, source="video_only.mp4", source_kind="file")
    with pytest.raises(MediaError, match="audio"):
        analyze_audio(video_only, cfg, media)


# ---------------------------------------------------------------------------
# L1: analyze_audio (the audio stage)
# ---------------------------------------------------------------------------


def test_analyze_audio_contract(planted):
    cfg = _cfg()
    media = build_media(planted, cfg, source="planted.mp4", source_kind="file")
    info = analyze_audio(planted, cfg, media)
    assert info.document_schema == "audio-info"
    assert info.sample_rate == RATE
    assert info.window_ms == WINDOW_MS
    assert info.window_samples == round(RATE * WINDOW_S)
    assert info.windows == 80
    assert len(info.rms) == len(info.energy) == info.windows
    assert info.offset_seconds == 0.0
    assert info.analyzed_seconds == pytest.approx(4.0)
    assert info.loudness.integrated_lufs is not None
    assert info.peaks.sample_count == 4 * RATE
    assert len(info.silence) == 2
    assert info.silence[0].start == pytest.approx(0.0, abs=WINDOW_S)
    assert info.silence[0].end == pytest.approx(0.5, abs=WINDOW_S)
    assert info.silence[1].end == pytest.approx(4.0, abs=WINDOW_S)


def test_analyze_audio_contract_serializes_clean(planted):
    cfg = _cfg()
    media = build_media(planted, cfg, source="planted.mp4", source_kind="file")
    info = analyze_audio(planted, cfg, media)
    raw = json.loads(dump_str(info))
    assert raw["schema"] == "audio-info"
    assert check_contract(raw) == []


def test_analyze_audio_deterministic(planted):
    cfg = _cfg()
    media = build_media(planted, cfg, source="planted.mp4", source_kind="file")
    assert dump_str(analyze_audio(planted, cfg, media)) == dump_str(
        analyze_audio(planted, cfg, media)
    )


def test_staged_equals_whole_file_slice(planted):
    full_media = build_media(planted, _cfg(), source="planted.mp4", source_kind="file")
    staged_cfg = _cfg(audio={"analyze_start": 0.5, "analyze_end": 2.0})
    staged_media = build_media(planted, staged_cfg, source="planted.mp4", source_kind="file")
    full = analyze_audio(planted, _cfg(), full_media)
    staged = analyze_audio(planted, staged_cfg, staged_media)
    start_w, end_w = int(round(0.5 / WINDOW_S)), int(round(2.0 / WINDOW_S))
    assert staged.rms == pytest.approx(full.rms[start_w:end_w])
    assert staged.offset_seconds == 0.5
    assert staged.silence == []  # window holds only the tone


# ---------------------------------------------------------------------------
# L2/L5: analyze_video writes analysis.json.audio
# ---------------------------------------------------------------------------


def test_analyze_video_audio_section(tmp_path, planted):
    project = tmp_path / "proj"
    cfg = build_config(overrides={"project": {"dir": str(project)}, "media": {"min_duration": 1.0}})
    media, project_dir = analyze_video(str(planted), cfg)
    assert project_dir == project
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["schema"] == "analysis"
    assert analysis["media"]["width"] == media.width
    audio = analysis["audio"]
    assert audio["schema"] == "audio-info"
    assert audio["silence"][0]["start"] == pytest.approx(0.0, abs=0.05)
    assert audio["silence"][0]["end"] == pytest.approx(0.5, abs=0.05)
    assert audio["silence"][1]["start"] == pytest.approx(2.0, abs=0.05)
    assert audio["silence"][1]["end"] == pytest.approx(4.0, abs=0.05)
    assert check_contract(analysis) == []


def test_analyze_video_audio_deterministic(tmp_path, planted):
    project = tmp_path / "proj"
    cfg = build_config(
        overrides={
            "project": {"dir": str(project), "overwrite": True},
            "media": {"min_duration": 1.0},
        }
    )
    analyze_video(str(planted), cfg)
    first = (project / "analysis.json").read_bytes()
    analyze_video(str(planted), cfg)
    assert (project / "analysis.json").read_bytes() == first
