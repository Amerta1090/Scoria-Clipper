"""Project-dir IO: stable JSON serialization contract + manifest writer."""

from scoria.project.jsonio import (
    FLOAT_DECIMALS,
    check_contract,
    dump_str,
    normalize,
    read_json,
    write_json,
)
from scoria.project.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    build_manifest,
    write_manifest,
)

__all__ = [
    "FLOAT_DECIMALS",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "build_manifest",
    "check_contract",
    "dump_str",
    "normalize",
    "read_json",
    "write_json",
    "write_manifest",
]
