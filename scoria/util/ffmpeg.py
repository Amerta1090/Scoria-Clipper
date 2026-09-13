"""Deterministic ffmpeg/ffprobe runner and capability detection.

Every subprocess invocation in the pipeline goes through here (ARCHITECTURE.md §3):
fixed positional args, `-nostdin` pinned, stderr captured for actionable failure
messages, env passed explicitly by the caller for later pinning.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from shutil import which
from typing import Any

from scoria.errors import MissingDependencyError, PipelineError

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"
_VERSION_TIMEOUT = 30


def _find(binary: str) -> str:
    path = which(binary)
    if path is None:
        raise MissingDependencyError(f"{binary} not found on PATH")
    return path


def version(binary: str) -> dict[str, Any] | None:
    """Return {'binary', 'version'} for a tool, or None when absent/unparseable."""
    path = which(binary)
    if path is None:
        return None
    try:
        proc = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=_VERSION_TIMEOUT
        )
        first = (proc.stdout or "").splitlines()[0] if proc.returncode == 0 else ""
    except OSError:
        return None
    if not first:
        return None
    return {"binary": path, "version": first}


def run_ffmpeg(
    args: Sequence[str],
    *,
    binary: str = FFMPEG_BIN,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run an ffmpeg-style binary with `-nostdin` pinned; raise PipelineError on failure."""
    path = _find(binary)
    full_args = [path, "-nostdin", *args]
    proc = subprocess.run(
        full_args,
        capture_output=True,
        text=True,
        env=env if env is not None else os.environ.copy(),
        timeout=timeout,
    )
    if proc.returncode != 0:
        tail_lines = (proc.stderr or "").strip().splitlines()[-15:]
        tail = "\n".join(tail_lines) if tail_lines else "(no stderr)"
        raise PipelineError(f"{binary} failed with exit {proc.returncode}", hint=tail)
    return proc


def has_filter(name: str) -> bool:
    """True when ffmpeg reports the named filter (e.g. `subtitles` => libass present)."""
    try:
        path = _find(FFMPEG_BIN)
    except MissingDependencyError:
        return False
    try:
        proc = subprocess.run(
            [path, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
        )
    except OSError:
        return False
    if proc.returncode != 0:
        return False
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False
