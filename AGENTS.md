# AGENTS.md

This repo is operated through an agent prompt. Read these first, in order:

1. `prompt.md` — project context, session protocol, commit conventions, Definition of Done.
2. `SPRINT_STATUS.md` — where work stopped (current sprint, next action, drift).

Ground truth docs live in `docs/` (see the list in `prompt.md`). `docs/DECISIONS.md` is append-only.

Quick start for a session: `git log --oneline -12` → `SPRINT_STATUS.md` → work the current sprint →
`ruff` + `pytest` → commit → update SPRINT_STATUS.

Environment note: this machine is Arch-based (Archcraft) with ffmpeg 9.0.1 preinstalled; whisper.cpp and
uv are not installed yet (see `docs/DEPENDENCIES.md`).