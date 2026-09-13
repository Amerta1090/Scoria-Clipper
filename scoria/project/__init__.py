"""Project-dir IO: stable JSON serialization contract + manifest writer + dir resolution."""

from scoria.project.dirs import (
    DEFAULT_TEMP_NAME,
    prepare_project_dir,
    project_temp_dir,
    resolve_project_dir,
)
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
    "DEFAULT_TEMP_NAME",
    "FLOAT_DECIMALS",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "build_manifest",
    "check_contract",
    "dump_str",
    "normalize",
    "prepare_project_dir",
    "project_temp_dir",
    "read_json",
    "resolve_project_dir",
    "write_json",
    "write_manifest",
]
