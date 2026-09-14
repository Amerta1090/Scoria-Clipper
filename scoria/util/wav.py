"""Minimal 32-bit-float WAV writer for the whisper bridge.

whisper-cli cannot read mp4/m4a/aac — the bridge decodes to PCM via `extract_pcm`
(identical to the audio stage) and hands whisper a 16 kHz mono IEEE-float WAV. Only
codec-3 (f32) writes are needed: whisper-cli's miniaudio decoder accepts them, and
the format is unambiguous (no endianness/sample-size guessing for the consumer).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def write_wav_f32(path: Path, samples: np.ndarray, *, rate: int) -> Path:
    """Write `samples` (float32, mono, [-1, 1]) as an IEEE-float WAV at `rate`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.asarray(samples, dtype=np.float32)
    n = pcm.shape[0]
    byte_rate = rate * 4
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + n * 4,
        b"WAVE",
        b"fmt ",
        16,
        3,  # IEEE float
        1,  # mono
        rate,
        byte_rate,
        4,  # block align
        32,  # bits per sample
        b"data",
        n * 4,
    )
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(pcm.tobytes())
    return path
