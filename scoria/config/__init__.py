"""Configuration: schema, defaults, profiles, merge + validation."""

from scoria.config.load import (
    build_config,
    deep_merge,
    default_config,
    dump_yaml,
    load_yaml,
    parse_config,
)
from scoria.config.profiles import PROFILES
from scoria.config.schema import (
    TRANSCRIPT_DISABLED_TERMS,
    ScoriaConfig,
    ScoringConfig,
    TranscriptConfig,
)

__all__ = [
    "PROFILES",
    "TRANSCRIPT_DISABLED_TERMS",
    "ScoriaConfig",
    "ScoringConfig",
    "TranscriptConfig",
    "build_config",
    "default_config",
    "deep_merge",
    "dump_yaml",
    "load_yaml",
    "parse_config",
]
