"""Stable JSON serialization contract (ADR-010, ARCHITECTURE.md §6).

One writer/reader pair for every runtime JSON artifact: keys sorted, floats rounded to 4
decimals, no trailing whitespace on lines, a single trailing newline, atomic writes.
Round-trip guarantees: serialize -> parse -> serialize is byte-identical.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from scoria.errors import PipelineError

FLOAT_DECIMALS = 4
_INDENT = 2


def _round_float(value: float) -> float:
    rounded = round(value, FLOAT_DECIMALS)
    if not math.isfinite(rounded):
        raise PipelineError(
            f"non-finite float {value!r} cannot be serialized — determinism is unrepresentable"
        )
    return rounded


def normalize(obj: Any) -> Any:
    """Recursively convert to a plain, contract-safe structure (no numpy, pydantic, / tuples)."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="python")
    if isinstance(obj, dict):
        return {str(key): normalize(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(value) for value in obj]
    if isinstance(obj, np.ndarray):
        return [normalize(value) for value in obj.tolist()]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return _round_float(float(obj))
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return _round_float(obj)
    if isinstance(obj, str):
        return obj
    raise PipelineError(f"cannot serialize value of type {type(obj).__name__}")


def dump_str(obj: Any) -> str:
    """Serialize to the contract JSON string (sorted keys, 4-decimal floats)."""
    return json.dumps(normalize(obj), ensure_ascii=False, sort_keys=True, indent=_INDENT)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_json(path: Path, obj: Any) -> Path:
    """Write an artifact under the serialization contract (atomic temp -> replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, dump_str(obj) + "\n")
    return path


def read_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise PipelineError(f"cannot read artifact {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"invalid JSON in {path}: {exc}") from exc


def check_contract(obj: Any, *, num_decimals: int = FLOAT_DECIMALS) -> list[str]:
    """Return violations of the serialization contract (for tests and golden diffs)."""
    violations: list[str] = []
    _check_contract(obj, num_decimals, (), violations)
    return violations


def _check_contract(obj: Any, num_decimals: int, path: tuple, violations: list[str]) -> None:
    if isinstance(obj, dict):
        keys = list(obj)
        sorted_keys = list(sorted(keys))
        if keys != sorted_keys:
            violations.append(f"keys not sorted at {'.'.join(map(str, path)) or '<root>'}")
        for key, value in obj.items():
            _check_contract(value, num_decimals, path + (key,), violations)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _check_contract(value, num_decimals, path + (index,), violations)
    elif isinstance(obj, bool) or obj is None or isinstance(obj, str) or isinstance(obj, int):
        return
    elif isinstance(obj, float):
        if obj != round(obj, num_decimals):
            violations.append(
                f"float not {num_decimals}-decimal at {'.'.join(map(str, path)) or '<root>'}"
            )
    else:
        violations.append(
            f"unserializable type {type(obj).__name__} at {'.'.join(map(str, path)) or '<root>'}"
        )
