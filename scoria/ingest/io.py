"""Input resolution: file vs stdin (`-`), with spooling.

Stdin media is spooled to a named file inside the project temp dir before any
probing — pipelines need a random-access file, not a one-shot pipe
(ARCHITECTURE.md §4, §5.1). The spool is the single decoded source later stages
re-use; it is not cleaned in Sprint 1 (the `--keep-temp` lifecycle lands with the
one-shot `run`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from scoria.errors import MediaError
from scoria.ingest.models import FILE_SOURCE, STDIN_SOURCE

_STDIN_NAME = "stdin.media"
_CHUNK = 1 << 16


def spool_stream(target: Path, stream: object) -> Path:
    """Copy a binary (or text) stream to `target`; return `target`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    read = getattr(stream, "read", None)
    if read is None:
        raise MediaError("stdin is not readable as a stream")
    with target.open("wb") as out:
        while True:
            chunk = read(_CHUNK)
            if not chunk:
                break
            out.write(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    if target.stat().st_size == 0:
        raise MediaError(
            "stdin delivered no bytes",
            hint="pipe media into `clipper analyze - -o DIR`",
        )
    return target


def resolve_input(video_arg: str, *, tmp_dir: Path) -> tuple[Path, str]:
    """Return (probeable file path, source_kind). Stdin is spooled into tmp_dir."""
    if video_arg == "-":
        target = spool_stream(tmp_dir / _STDIN_NAME, getattr(sys.stdin, "buffer", sys.stdin))
        return target, STDIN_SOURCE
    path = Path(video_arg)
    if not path.is_file():
        raise MediaError(
            f"input not found: {video_arg}",
            hint="check the path and try again",
        )
    return path, FILE_SOURCE
