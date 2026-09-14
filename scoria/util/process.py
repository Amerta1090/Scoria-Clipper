"""Generic subprocess runner for non-ffmpeg pipeline tools (ARCHITECTURE.md §3).

ffmpeg/ffprobe have their own pinned runner in `util/ffmpeg` (`-nostdin`). Other
tools differ: whisper-cli takes no `-nostdin`, but it only ever reads its `-f` input
file, so stdin is pinned to DEVNULL here — the same "never touch stdin" guarantee with
the tool's own flag surface. stderr is captured for an actionable failure hint.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from shutil import which

from scoria.errors import PipelineError

# whisper.cpp emits its JSON sidecar next to the input file: `<audio>.<ext>.json`.
WHISPER_JSON_SUFFIX = ".json"


def _find(binary: str) -> str:
    path = which(binary)
    if path is None:
        raise PipelineError(f"{binary} not found on PATH")
    return path


def run_tool(
    binary: str,
    args: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run a non-ffmpeg tool with stdin pinned to /dev/null; raise PipelineError on failure."""
    path = _find(binary)
    proc = subprocess.run(
        [path, *args],
        capture_output=True,
        text=True,
        env=env if env is not None else os.environ.copy(),
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        tail_lines = (proc.stderr or "").strip().splitlines()[-15:]
        tail = "\n".join(tail_lines) if tail_lines else "(no stderr)"
        raise PipelineError(f"{binary} failed with exit {proc.returncode}", hint=tail)
    return proc
