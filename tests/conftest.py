from pathlib import Path

import numpy as np
import pytest

from scoria.util.ffmpeg import run_ffmpeg

_MIN_DURATION_YAML = "media:\n  min_duration: 1.0\n"


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Enforce the offline contract: any outbound connect during tests fails loudly."""

    def guard(*args, **kwargs):
        raise RuntimeError("network access is blocked in scoria tests (offline contract)")

    monkeypatch.setattr("socket.socket.connect", guard)
    monkeypatch.setattr("socket.socket.connect_ex", lambda self, address: 1)
    monkeypatch.setattr("socket.create_connection", guard)


@pytest.fixture(scope="session")
def _media_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("media_fixtures")


def _gen_video(target: Path, *, size: str, duration: float = 3.0) -> None:
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={size}:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(target),
        ]
    )


def _gen_audio_only(target: Path, *, duration: float = 3.0) -> None:
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            str(duration),
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(target),
        ]
    )


def planted_samples(*, rate: int = 16000, duration: float = 4.0) -> np.ndarray:
    """Sine (440 Hz, amplitude 0.5) on [0.5, 2.0)s, silence everywhere else."""
    n = round(duration * rate)
    t = np.arange(n) / rate
    samples = np.zeros(n, dtype=np.float64)
    tone = (t >= 0.5) & (t < 2.0)
    samples[tone] = 0.5 * np.sin(2 * np.pi * 440.0 * t[tone])
    return samples.astype(np.float32)


def _write_wav(target: Path, samples: np.ndarray, *, rate: int) -> None:
    import wave

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


@pytest.fixture(scope="session")
def video_only(_media_dir):
    path = _media_dir / "video_only.mp4"
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-t",
            "3",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            str(path),
        ]
    )
    return path


@pytest.fixture(scope="session")
def planted_wav(_media_dir):
    path = _media_dir / "planted_silence.wav"
    _write_wav(path, planted_samples(), rate=16000)
    return path


@pytest.fixture(scope="session")
def planted(_media_dir, planted_wav):
    path = _media_dir / "planted.mp4"
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-i",
            str(planted_wav),
            "-t",
            "4",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(path),
        ]
    )
    return path


@pytest.fixture(scope="session")
def landscape(_media_dir):
    path = _media_dir / "landscape_16x9.mp4"
    _gen_video(path, size="640x360")
    return path


@pytest.fixture(scope="session")
def portrait(_media_dir):
    path = _media_dir / "portrait_9x16.mp4"
    _gen_video(path, size="360x640")
    return path


@pytest.fixture(scope="session")
def classic(_media_dir):
    path = _media_dir / "classic_4x3.mp4"
    _gen_video(path, size="640x480")
    return path


@pytest.fixture(scope="session")
def audio_only(_media_dir):
    path = _media_dir / "audio_only.m4a"
    _gen_audio_only(path)
    return path


@pytest.fixture
def min_cfg(tmp_path):
    """A minimal YAML config with media.min_duration lowered for short fixtures."""
    cfg = tmp_path / "min_duration.yaml"
    cfg.write_text(_MIN_DURATION_YAML, encoding="utf-8")
    return cfg
