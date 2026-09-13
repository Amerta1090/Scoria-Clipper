from pathlib import Path

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
