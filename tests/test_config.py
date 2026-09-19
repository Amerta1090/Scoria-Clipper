"""L0: config schema, defaults, merge order and validation rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from scoria.config import (
    PROFILES,
    build_config,
    deep_merge,
    default_config,
    dump_yaml,
    parse_config,
)
from scoria.errors import ConfigError

FIXTURES = Path(__file__).parent / "fixtures"

DEFAULT_ENABLED_SUM = 0.89


def test_default_config_loads_and_renormalizes():
    config = default_config()
    enabled = config.scoring.enabled_weights()
    assert abs(sum(enabled.values()) - DEFAULT_ENABLED_SUM) < 1e-9
    assert "face_presence" not in enabled


def test_default_renormalized_weights_sum_to_one():
    config = default_config()
    renorm = config.scoring.renormalized_weights()
    assert abs(sum(renorm.values()) - 1.0) < 1e-9
    expected = {
        name: w / DEFAULT_ENABLED_SUM for name, w in config.scoring.enabled_weights().items()
    }
    assert renorm == pytest.approx(expected)


def test_transcript_disabled_drops_speech_terms():
    config = default_config()
    renorm = config.scoring.renormalized_weights(transcript_enabled=False)
    assert not {"speech_density", "pacing", "hook", "keyword_density", "sentence_quality"} & set(
        renorm
    )
    assert abs(sum(renorm.values()) - 1.0) < 1e-9


def test_unknown_key_rejected():
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "surprise_key": True})


def test_unknown_key_from_fixture():
    with pytest.raises(ConfigError):
        build_config(path=FIXTURES / "config_unknown_key.yaml")


def test_negative_weight_rejected():
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "scoring": {"weights": {"audio_energy": -0.5}}})


def test_all_zero_weights_rejected():
    with pytest.raises(ConfigError):
        parse_config(
            {
                "version": 1,
                "scoring": {
                    "weights": {
                        name: 0.0
                        for name in (
                            "audio_energy",
                            "speech_density",
                            "pacing",
                            "hook",
                            "completeness",
                            "visual_activity",
                            "keyword_density",
                            "sentence_quality",
                            "face_presence",
                        )
                    }
                },
            }
        )


def test_segment_ordering_rejected():
    with pytest.raises(ConfigError):
        build_config(path=FIXTURES / "config_bad_segment.yaml")


def test_reframe_ratio_rejected():
    with pytest.raises(ConfigError):
        build_config(path=FIXTURES / "config_bad_reframe.yaml")


def test_reframe_odd_dims_rejected():
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "reframe": {"output": {"width": 1081, "height": 1920}}})


def test_silence_rule_rejected():
    with pytest.raises(ConfigError):
        build_config(path=FIXTURES / "config_silence_rule.yaml")


def test_unsupported_version_rejected():
    with pytest.raises(ConfigError):
        build_config(path=FIXTURES / "config_bad_version.yaml")


def test_partial_config_file_merges_over_defaults():
    config = build_config(path=FIXTURES / "config_good.yaml")
    assert config.media.frame.width == 96
    assert config.media.frame.fps == 4
    assert config.scoring.weights.completeness == 0.20


def test_bad_yaml_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        build_config(path=path)


def test_yaml_round_trip_parses(tmp_path):
    text = dump_yaml(default_config())
    path = tmp_path / "out.yaml"
    path.write_text(text, encoding="utf-8")
    config = build_config(path=path)
    assert config == default_config()


def test_deep_merge_nested():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    merged = deep_merge(base, {"a": {"y": 9, "z": 4}, "b": 0})
    assert merged == {"a": {"x": 1, "y": 9, "z": 4}, "b": 0}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3}


def test_profiles_change_documented_weights():
    default_weights = default_config().scoring.weights.as_dict()
    expected_directions = {
        "podcast": {
            "speech_density": 1,
            "visual_activity": -1,
            "audio_energy": 1,
            "keyword_density": -1,
        },
        "lecture": {"completeness": 1, "hook": -1, "pacing": -1, "speech_density": 1},
        "interview": {"sentence_quality": 1, "hook": 1, "audio_energy": -1},
        "gaming": {"visual_activity": 1, "hook": 1, "speech_density": -1, "keyword_density": -1},
        "talking-head": {"audio_energy": -1, "visual_activity": -1, "completeness": 1},
    }
    for name, deltas in expected_directions.items():
        for term, direction in deltas.items():
            moved = PROFILES[name]["scoring"]["weights"][term]
            if direction > 0:
                assert moved > default_weights[term], f"profile {name}: {term} should rise"
            else:
                assert moved < default_weights[term], f"profile {name}: {term} should fall"


def test_podcast_profile_direction():
    config = build_config(profile="podcast")
    weights = config.scoring.weights
    assert weights.speech_density > 0.13
    assert weights.visual_activity < 0.10


def test_unknown_profile_rejected():
    with pytest.raises(ConfigError):
        build_config(profile="nope")


def test_cli_overrides_merge_last(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("transcript:\n  enabled: true\n", encoding="utf-8")
    config = build_config(path=path, overrides={"transcript": {"enabled": False}})
    assert config.transcript.enabled is False


def test_focus_bounds():
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "reframe": {"focus": {"x": 1.5, "y": 0.5}}})


# ---------------------------------------------------------------------------
# Sprint 12: gamer reframe config (reframe.gamer)
# ---------------------------------------------------------------------------


def test_gamer_defaults_valid_and_inside_unit_square():
    gamer = default_config().reframe.gamer
    assert 0.0 < gamer.gameplay.v_fraction < 1.0
    assert gamer.gameplay.anchor == "center"
    region = gamer.facecam.region
    assert region.x + region.w <= 1.0 + 1e-9
    assert region.y + region.h <= 1.0 + 1e-9
    for value in (region.x, region.y, region.w, region.h):
        assert 0.0 <= value <= 1.0


def test_gaming_profile_selects_gamer_mode():
    config = build_config(profile="gaming")
    assert config.reframe.mode == "gamer"


def test_gamer_v_fraction_bounds_rejected():
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "reframe": {"gamer": {"gameplay": {"v_fraction": 1.0}}}})
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "reframe": {"gamer": {"gameplay": {"v_fraction": 0.0}}}})
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "reframe": {"gamer": {"gameplay": {"v_fraction": -0.2}}}})


def test_gamer_region_must_fit_unit_square():
    with pytest.raises(ConfigError):
        parse_config(
            {"version": 1, "reframe": {"gamer": {"facecam": {"region": {"x": 0.9, "w": 0.2}}}}}
        )
    with pytest.raises(ConfigError):
        parse_config(
            {"version": 1, "reframe": {"gamer": {"facecam": {"region": {"y": 0.9, "h": 0.2}}}}}
        )


def test_gamer_region_zero_size_rejected():
    with pytest.raises(ConfigError):
        parse_config({"version": 1, "reframe": {"gamer": {"facecam": {"region": {"w": 0.0}}}}})
