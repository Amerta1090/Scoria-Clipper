"""Error taxonomy: every error carries an exit code and an optional user hint.

Exit codes follow CLI_SPEC.md: 0 ok, 1 pipeline error, 2 config/usage error.
"""

from __future__ import annotations


class ScoriaError(Exception):
    """Base error. `exit_code` maps to the process exit code (CLI_SPEC §1)."""

    exit_code = 1

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class PipelineError(ScoriaError):
    """A runtime pipeline failure (media, artifacts, subprocesses). Exit 1."""

    exit_code = 1


class MediaError(PipelineError):
    """Input media could not be probed or validated (exit 1), with ffprobe detail."""

    exit_code = 1


class MissingDependencyError(PipelineError):
    """A required external tool is absent. Exit 1, with a verify-env hint."""

    exit_code = 1

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message, hint=hint or "run `clipper verify-env` to check your environment")


class TranscriptError(PipelineError):
    """The STT pipeline failed at runtime (model checksum, tool failure, parse). Exit 1."""

    exit_code = 1


class ConfigError(ScoriaError):
    """Invalid configuration (unknown key, validation failure, bad YAML). Exit 2."""

    exit_code = 2


class UsageError(ScoriaError):
    """Invalid CLI usage. Exit 2."""

    exit_code = 2
