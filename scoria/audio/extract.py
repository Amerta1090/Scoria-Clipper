"""PCM extraction + ebur128 loudness via the pinned ffmpeg runner.

Decode path: `ffmpeg -i IN -vn -ac 1 -ar RATE -f f32le -` → one mono float32 array
whose samples are already scaled to [-1, 1] by ffmpeg (f32le output is normalized;
documented float32 range). Fixed flags only; every subprocess call goes through the
deterministic runner in `util/ffmpeg` (ARCHITECTURE.md §3, §5.1).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from scoria.audio.models import LoudnessInfo
from scoria.errors import MediaError, PipelineError
from scoria.util.ffmpeg import run_ffmpeg, run_ffmpeg_binary

# ebur128 summary values (numeric only — stable across builds; pointer addresses in
# stderr are never parsed or stored) from:
#   [Parsed_ebur128_0 @ ...] Summary:
#     Integrated loudness:        I: -19.4 LUFS
#     True peak:                  Peak: -1.2 dBFS
_INTEGRATED_RE = re.compile(r"\bI:\s+(-?\d+(?:\.\d+)?)\s*LUFS")
_TRUE_PEAK_RE = re.compile(r"\bPeak:\s+(-?\d+(?:\.\d+)?)\s*dBFS")


def extract_pcm(path: Path, *, rate: int) -> np.ndarray:
    """Decode the file to one mono float32 array at `rate` (samples in [-1, 1])."""
    try:
        raw = run_ffmpeg_binary(
            [
                "-v",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(rate),
                "-f",
                "f32le",
                "-",
            ]
        )
    except PipelineError as exc:
        raise MediaError(
            f"no audio stream decodable from {path.name}",
            hint=exc.hint,
        ) from exc
    samples = np.frombuffer(raw, dtype=np.float32)
    if samples.shape[0] == 0:
        raise MediaError(
            f"no audio samples decoded from {path.name}",
            hint="the file has no audio track that ffmpeg can decode",
        )
    return samples


def measure_loudness(path: Path, *, rate: int) -> LoudnessInfo:
    """ebur128 integrated loudness (+ true peak) over the whole file.

    Used only as information and for the render normalization gain (ADR-005); a
    missing/oddly-formatted summary yields `None` fields rather than a failure.
    """
    proc = run_ffmpeg(
        [
            "-v",
            "info",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-af",
            "ebur128",
            "-f",
            "null",
            "-",
        ]
    )
    stderr = proc.stderr or ""
    # ebur128 streams per-window stats then a final "Summary:" block; only the
    # summary carries the integrated/true-peak measurements. Parse the tail so the
    # per-window progress lines (e.g. an early "I: -70.0 LUFS" silence sample)
    # never shadow the summary values.
    summary = stderr.partition("Summary:")[2]
    integrated = _INTEGRATED_RE.search(summary)
    peak = _TRUE_PEAK_RE.search(summary)
    return LoudnessInfo(
        integrated_lufs=float(integrated.group(1)) if integrated else None,
        true_peak_db=float(peak.group(1)) if peak else None,
    )
