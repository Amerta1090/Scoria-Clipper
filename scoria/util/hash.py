"""Streaming sha256 helper for the whisper model checksum (ADR-004, CONFIGURATION.md)."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """Return the lowercase hex sha256 of `path`, read in bounded chunks (487 MB model)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
