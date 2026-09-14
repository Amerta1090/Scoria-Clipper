"""`clipper verify-env`: zero-network environment self-check.

Required (exit 1 if missing): ffmpeg + ffprobe. Optional (warn only): whisper-cli +
its model, libass (subtitles filter), numpy, Python version. Never phones home.
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np

from scoria import __version__
from scoria.config import build_config, default_config
from scoria.errors import ConfigError
from scoria.transcript import whisper_cli_info, whisper_model_info
from scoria.util import ffmpeg

REQUIRED_TOOLS = ("ffmpeg", "ffprobe")


def check() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for tool in REQUIRED_TOOLS:
        info = ffmpeg.version(tool)
        tools[tool] = {
            "present": info is not None,
            "version": info["version"] if info else None,
            "binary": info["binary"] if info else None,
        }
    tools["python"] = {
        "present": True,
        "version": sys.version.split()[0],
        "binary": sys.executable,
    }
    tools["numpy"] = {
        "present": True,
        "version": np.__version__,
        "binary": None,
    }
    try:
        cfg = build_config()
    except ConfigError:
        cfg = default_config()
    whisper = whisper_cli_info(cfg.transcript)
    tools["whisper_cli"] = {
        "present": whisper is not None,
        "version": whisper["version"] if whisper else None,
        "binary": whisper["binary"] if whisper else None,
    }
    model = whisper_model_info(cfg.transcript)
    tools["whisper_model"] = {
        "present": bool(model["sha256"]),
        "version": None,
        "binary": model["path"],
    }
    tools["libass"] = {"present": ffmpeg.has_filter("subtitles"), "version": None, "binary": None}
    return {
        "scoria": __version__,
        "required_ok": all(tools[t]["present"] for t in REQUIRED_TOOLS),
        "tools": tools,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [f"scoria {report['scoria']}"]
    for name, info in report["tools"].items():
        state = "ok" if info["present"] else "missing"
        version = info["version"] or ""
        binary = info["binary"] or ""
        lines.append(f"{name:12} {version:18} {state:8} {binary}")
    lines.append("required (ffmpeg + ffprobe): " + ("OK" if report["required_ok"] else "MISSING"))
    return "\n".join(lines).rstrip()
