# scoria

Deterministic, local-first video clipping engine. One command:

```
clipper video.mp4 --top 3
```

→ ranked 9:16 vertical clips with burned-in captions. Local-only, no cloud APIs, no
AI in the scoring path — measurable signals, configurable scoring, reproducible output.

## What it does

`clipper` drives the whole pipeline in one shot: probe the video (ffprobe), extract
audio / visual / transcript signals, segment into candidate windows, score them with the
configurable engine, pick a diverse top-N, build captions (whisper.cpp → SRT/ASS karaoke),
reframe to 9:16, render the clips with ffmpeg, and write a self-contained `report.html`
with previews. Same inputs + same config → identical bytes (no RNG anywhere).

## Quick start

```bash
uv sync                                     # create the venv, install the clipper CLI
uv run clipper verify-env                   # offline tool check (ffmpeg/ffprobe/whisper/libass)
uv run clipper fetch-model                  # one-time whisper model download (network op)
uv run clipper video.mp4 --top 3            # one-shot: clips/ + captions/ + report.html
```

Requires Python ≥ 3.12, ffmpeg + ffprobe, and whisper.cpp for captions (full stack:
`docs/DEPENDENCIES.md`). Scoring and staging work without STT — pass `--no-transcript`
(and `--no-visual` to skip the frame pass).

## Project layout

`clipper video.mp4 -o proj` writes every stage artifact into `proj/`, and each stage
command (`analyze`, `segment`, `score`, `rank`, `render`, `report`, `explain`, …) can
read them back for inspection and tuning between steps:

| Artifact | Contents |
|---|---|
| `analysis.json` | media metadata + audio/visual/transcript features |
| `candidates.json` | raw candidate windows (unscored) |
| `ranking.json` | diverse top-N selection + marginal-gain decisions |
| `reframe.json` | 9:16 crop / blur-pad geometry |
| `clips/` | rendered `<id>.mp4` (1080×1920) |
| `captions/` | SRT + ASS sidecars + `captions.json` |
| `previews/` + `report.html` | clip stills, timeline strip, self-contained report |

## Docs

Ground truth lives in `docs/` — read `prompt.md` first for the operating protocol, then
`docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/CLI_SPEC.md`, `docs/CONFIGURATION.md`, and friends.