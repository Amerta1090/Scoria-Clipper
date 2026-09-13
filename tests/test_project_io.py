"""L0: serialization contract (ARCHITECTURE.md §6, ADR-010).

Sorted keys, 4-decimal floats, byte-stable across serialize → parse → serialize cycles.
"""

from __future__ import annotations

import numpy as np
import pytest

from scoria.config import default_config
from scoria.errors import PipelineError
from scoria.project import (
    build_manifest,
    check_contract,
    dump_str,
    normalize,
    read_json,
    write_json,
    write_manifest,
)

SAMPLE = {
    "media": {"duration": 0.123456789, "wpm": 160.0},
    "audio": {"rms": [0.5, 1.0000001], "silence": None},
    "name": "x",
    "flag": True,
    "n": 7,
}


def test_two_roundtrip_cycles_byte_identical(tmp_path):
    path = tmp_path / "a.json"
    write_json(path, SAMPLE)
    first = path.read_text()
    for _ in range(2):
        write_json(path, read_json(path))
    assert path.read_text() == first


def test_second_roundtrip_identical_to_first_dump(tmp_path):
    path = tmp_path / "a.json"
    write_json(path, SAMPLE)
    assert dump_str(read_json(path)) == dump_str(SAMPLE)


def test_floats_pinned_to_4_decimals(tmp_path):
    path = tmp_path / "f.json"
    write_json(path, {"x": 0.123456789})
    text = path.read_text()
    assert "0.1235" in text
    assert "0.123456789" not in text


def test_keys_sorted_and_contract_clean(tmp_path):
    path = tmp_path / "s.json"
    write_json(path, {"z": 1, "a": {"y": 1, "b": 2}})
    loaded = read_json(path)
    assert list(loaded) == ["a", "z"]
    assert list(loaded["a"]) == ["b", "y"]
    assert check_contract(loaded) == []


def test_numpy_objects_serialize(tmp_path):
    path = tmp_path / "n.json"
    write_json(
        path,
        {
            "arr": np.array([0.1, 0.1234567], dtype=np.float32),
            "scalar": np.float32(1.5),
            "integer": np.int64(3),
        },
    )
    loaded = read_json(path)
    assert loaded == {"arr": [0.1, 0.1235], "scalar": 1.5, "integer": 3}


def test_pydantic_model_serializes(tmp_path):
    path = tmp_path / "p.json"
    write_json(path, default_config())
    assert read_json(path)["scoring"]["weights"]["completeness"] == 0.2


def test_nonfinite_float_rejected(tmp_path):
    with pytest.raises(PipelineError):
        write_json(tmp_path / "nan.json", {"x": float("nan")})
    with pytest.raises(PipelineError):
        write_json(tmp_path / "inf.json", {"x": float("inf")})


def test_normalize_rejects_unknown_type():
    with pytest.raises(PipelineError):
        normalize(object())


def test_contract_check_flags_violations():
    assert check_contract({"a": 1, "z": 2}) == []
    assert check_contract({"a": 1}, num_decimals=4) == []
    assert check_contract({"z": 1, "a": 2}) != []
    assert check_contract({"x": 0.123456}) != []


def test_writer_is_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "a.json"
    for _ in range(3):
        write_json(path, SAMPLE)
    assert not (tmp_path / "a.json.tmp").exists()


def test_manifest_contains_stamps_and_is_deterministic():
    config = default_config()
    tools = {"ffmpeg": {"version": "n9.0.1"}, "ffprobe": {"version": "n9.0.1"}}
    first = build_manifest(
        config=config, tools=tools, invocation=["clipper", "video.mp4", "--top", "3"]
    )
    second = build_manifest(
        config=config, tools=tools, invocation=["clipper", "video.mp4", "--top", "3"]
    )
    assert dump_str(first) == dump_str(second)
    assert first["schema"] == "project-manifest"
    assert first["scoring_version"] == "1.0.0"
    assert first["degraded"] == []
    assert first["deterministic"] is True
    assert first["config"]["scoring"]["weights"]["completeness"] == 0.2


def test_manifest_degraded_sorted_and_stable():
    config = default_config()
    tools = {"ffmpeg": None}
    manifest = build_manifest(
        config=config, tools=tools, invocation=["x"], degraded=["transcript", "visual"]
    )
    assert manifest["degraded"] == ["transcript", "visual"]


def test_manifest_written(tmp_path):
    config = default_config()
    path = write_manifest(tmp_path, config=config, tools={"ffmpeg": None}, invocation=["y"])
    assert path.name == "manifest.json"
    back = read_json(path)
    assert back["schema"] == "project-manifest"
    assert back["python"].startswith("3.")
