"""manifest.json writer.

Every run stamps tool versions, the active config snapshot, SCORING_VERSION, the invocation
and any degraded flags so drift between runs is diagnosable. The manifest is deliberately
free of wall-clock timestamps: it is part of the deterministic corpus (ARCHITECTURE.md §7)
— generation hashes must not differ just because a run happened later.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from scoria import __version__
from scoria.config.schema import ScoriaConfig
from scoria.project.jsonio import normalize, write_json

MANIFEST_SCHEMA = "project-manifest"
MANIFEST_FILENAME = "manifest.json"


def build_manifest(
    *,
    config: ScoriaConfig,
    tools: dict[str, dict[str, Any] | None],
    invocation: Sequence[str],
    scoring_version: str | None = None,
    degraded: Iterable[str] = (),
    deterministic: bool = True,
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "scoria": __version__,
        "python": sys.version.split()[0],
        "scoring_version": scoring_version or config.scoring.version,
        "tools": normalize(tools),
        "config": config.model_dump(mode="python"),
        "invocation": list(invocation),
        "degraded": sorted(set(degraded)),
        "deterministic": deterministic,
    }


def write_manifest(
    project_dir: Path,
    *,
    config: ScoriaConfig,
    tools: dict[str, dict[str, Any] | None],
    invocation: Sequence[str],
    scoring_version: str | None = None,
    degraded: Iterable[str] = (),
    deterministic: bool = True,
) -> Path:
    manifest = build_manifest(
        config=config,
        tools=tools,
        invocation=invocation,
        scoring_version=scoring_version,
        degraded=degraded,
        deterministic=deterministic,
    )
    return write_json(Path(project_dir) / MANIFEST_FILENAME, manifest)
