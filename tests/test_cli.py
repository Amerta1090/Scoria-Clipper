"""L5: CLI surface — exit codes, config round-trip, verify-env reports versions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from scoria.cli.main import app
from scoria.config import default_config, dump_yaml

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent


def _output(result) -> str:
    return result.output + str(getattr(result, "stderr", ""))


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "scoria" in result.output


def test_no_args_shows_help():
    proc = subprocess.run(
        [sys.executable, "-m", "scoria.cli"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "Commands" in proc.stdout


def test_one_shot_run_stub_exits_one():
    result = runner.invoke(app, ["run", "video.mp4", "--top", "3"])
    assert result.exit_code == 1
    assert "not implemented" in result.output


def test_stage_stub_analyze_exits_one():
    result = runner.invoke(app, ["analyze", "video.mp4"])
    assert result.exit_code == 1
    assert "not implemented" in result.output


def test_unknown_flag_exits_two():
    result = runner.invoke(app, ["--bogus"])
    assert result.exit_code == 2


def test_config_validate_round_trips_write_defaults(tmp_path):
    default_yaml = runner.invoke(app, ["config", "write-defaults"])
    assert default_yaml.exit_code == 0
    config_file = tmp_path / "default.yaml"
    config_file.write_text(default_yaml.output, encoding="utf-8")
    result = runner.invoke(app, ["config", "validate", str(config_file)])
    assert result.exit_code == 0
    assert "config ok" in result.output


def test_config_validate_accepts_partial_file():
    result = runner.invoke(app, ["config", "validate", str(FIXTURES / "config_good.yaml")])
    assert result.exit_code == 0
    assert "config ok" in result.output


def test_config_validate_unknown_key_exits_two():
    result = runner.invoke(app, ["config", "validate", str(FIXTURES / "config_unknown_key.yaml")])
    assert result.exit_code == 2
    assert "error" in _output(result).lower()


def test_config_show_dumps_valid_yaml():
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "scoring" in result.output
    assert "version: 1" in result.output


def test_config_write_defaults_matches_default_model():
    result = runner.invoke(app, ["config", "write-defaults"])
    assert result.exit_code == 0
    assert result.output == dump_yaml(default_config())


def test_verify_env_json_reports_versions():
    result = runner.invoke(app, ["verify-env", "--json"])
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["required_ok"] is True
    assert report["tools"]["ffmpeg"]["present"] is True
    assert report["tools"]["ffmpeg"]["version"]
    assert report["tools"]["ffprobe"]["present"] is True
    assert report["tools"]["python"]["version"].startswith("3.")


def test_verify_env_text_form():
    result = runner.invoke(app, ["verify-env"])
    assert result.exit_code == 0
    assert "ffmpeg" in result.output


def test_entry_wrapper_rewrites_one_shot():
    proc = subprocess.run(
        [sys.executable, "-m", "scoria.cli", "sample.mp4", "--top", "2"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "not implemented" in proc.stderr


def test_entry_passthrough_verify_env():
    proc = subprocess.run(
        [sys.executable, "-m", "scoria.cli", "verify-env", "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["required_ok"] is True


def test_entry_help_passthrough():
    proc = subprocess.run(
        [sys.executable, "-m", "scoria.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "Commands" in proc.stdout
