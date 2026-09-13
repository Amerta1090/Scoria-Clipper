# scoria

Deterministic, local-first video clipping engine. One command:

```
clipper video.mp4 --top 3
```

→ ranked 9:16 vertical clips with burned-in captions. Local-only, no cloud APIs, no
AI in the scoring path — measurable signals, configurable scoring, reproducible output.

## Status

Sprint 0 (repository foundation). The pipeline itself lands in Sprints 1–11.

## Quick start (open this repo)

```bash
uv sync          # create the venv and install the clipper CLI
uv run clipper --help
```

Requires Python ≥ 3.12 and `uv` (see `docs/DEPENDENCIES.md` for the full stack including ffmpeg).

```
uv run clipper verify-env        # report tool versions (zero network)
uv run clipper config show       # active merged config as YAML
uv run clipper config write-defaults > scoria.yaml   # bootstrap a config file
```

## Docs

Ground truth lives in `docs/` — read `prompt.md` first for the operating protocol, then
`docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, and friends.