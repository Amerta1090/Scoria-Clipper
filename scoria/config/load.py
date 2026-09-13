"""Config loading: defaults < profile < --config file < CLI overrides.

YAML is parsed with PyYAML, then validated against the pydantic schema. Any validation
failure (unknown key included) surfaces as a ConfigError -> exit code 2.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scoria.config.profiles import PROFILES
from scoria.config.schema import ScoriaConfig
from scoria.errors import ConfigError

DEFAULT_CONFIG_CANDIDATES = (
    Path(os.getcwd()) / "scoria.yaml",
    Path.home() / ".config" / "scoria" / "config.yaml",
)


def default_config() -> ScoriaConfig:
    return ScoriaConfig()


def deep_merge(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge; delta values replace base values at every key."""
    out = dict(base)
    for key, value in delta.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping, got {type(data).__name__} in {path}")
    return data


def dump_yaml(config: ScoriaConfig) -> str:
    return yaml.safe_dump(
        config.model_dump(mode="python"), sort_keys=True, default_flow_style=False
    )


def parse_config(data: dict[str, Any], *, source: str = "config") -> ScoriaConfig:
    try:
        return ScoriaConfig.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first["loc"]) or source
        raise ConfigError(
            f"{source}: {loc}: {first['msg']}",
            hint="fix the value, or run `clipper config validate <file>` for the full dump",
        ) from exc


def find_config_file(*, explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def build_config(
    *,
    path: Path | None = None,
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> ScoriaConfig:
    """Merge and validate the active config. Merge order: defaults < profile < file < CLI."""
    data = default_config().model_dump(mode="python")
    sources = []
    if profile is not None:
        if profile not in PROFILES:
            raise ConfigError(f"unknown profile {profile!r}; choose from {sorted(PROFILES)}")
        data = deep_merge(data, PROFILES[profile])
        sources.append(f"profile:{profile}")
    config_file = find_config_file(explicit=path)
    if config_file is not None:
        data = deep_merge(data, load_yaml(config_file))
        sources.append(str(config_file))
    if overrides:
        data = deep_merge(data, overrides)
        sources.append("cli")
    caller = " + ".join(sources) if sources else "defaults"
    return parse_config(data, source=caller)
