# scoria

Deterministic, local-first video clipping engine. It takes a long video and produces
shorter videos out of it. That is the whole pitch, so do not go looking for a second act.

No cloud APIs, no "AI-powered" anything. The scoring path is plain, configurable math,
because the authors would like to be able to explain the output to another human without
crying.

## What it does

One command drives the whole pipeline:

```
clipper video.mp4 --top 3
```

(Shorthand for `clipper run video.mp4 --top 3`. The CLI is polite about it.)

Which runs: probe the file, extract audio / visual / transcript signals, cut candidate
windows, score them, pick a diverse top-N, build karaoke captions, reframe to 9:16,
render the clips with ffmpeg, and write a self-contained `report.html`.

Same input + same config = same bytes, every time. There is no RNG anywhere in the
pipeline, so there is nobody to blame when the bytes differ — they cannot differ. Run it
twice if you do not believe it; the output will be identical and the second run will be
about as exciting as the first.

## Quick start

```bash
uv sync                                     # create the venv, install the clipper CLI
uv run clipper verify-env                   # offline tool check (ffmpeg/ffprobe/whisper/libass)
uv run clipper fetch-model                  # one-time whisper model download (network op)
uv run clipper video.mp4 --top 3            # one-shot: clips/ + captions/ + report.html
```

Requires Python >= 3.12, ffmpeg + ffprobe, and whisper.cpp if you want captions. Full
stack: `docs/DEPENDENCIES.md`.

You can run the whole thing without speech-to-text: `--no-transcript` skips STT,
`--no-visual` skips the frame pass, and `--no-captions` skips burning text into the
clips. These are not workarounds. They are the documented degraded modes, and they are
tested. If you do not have whisper installed and you forget `--no-transcript`, the tool
will exit with a clear error, loudly, on purpose, instead of quietly producing half a
pipeline and calling it a day.

Exit codes are meaningful, because somebody had to decide that they would be:

| Code | Meaning |
|---|---|
| 0 | worked |
| 1 | input missing, or STT missing |
| 2 | you asked for something that does not exist yet (e.g. `--no-vertical`) |

Reframing in the MVP is 9:16 center crop. Focus modes (faces, targets, "intelligent
cropping") are a post-MVP rumor; requesting them is an exit code, not a feature.

## Project layout

`clipper video.mp4 -o proj` writes every stage artifact into `proj/`, and each stage
command (`analyze`, `segment`, `score`, `rank`, `reframe`, `render`, `report`,
`explain`, ...) can read them back, for people who enjoy watching their pipeline in
slow motion:

| Artifact | Contents |
|---|---|
| `analysis.json` | media metadata + audio/visual/transcript features |
| `candidates.json` | raw candidate windows (unscored) |
| `ranking.json` | diverse top-N selection + marginal-gain decisions |
| `reframe.json` | 9:16 crop / blur-pad geometry |
| `clips/` | rendered `<id>.mp4` (1080x1920) |
| `captions/` | SRT + ASS sidecars + `captions.json` |
| `previews/` + `report.html` | clip stills, timeline strip, self-contained report |

## License

MIT. See `LICENSE`.

## Docs

Ground truth lives in `docs/`. Recommended reading order, for the completionists:

- `docs/PRD.md` — what this is for
- `docs/CLI_SPEC.md` — every flag, including the ones that just fail
- `docs/CONFIGURATION.md` — the knobs; scoring is 100 % config-driven
- `docs/ARCHITECTURE.md` — how it is put together
- `docs/SCORING_ENGINE.md` — the math, equations included
- `docs/SIGNALS.md`, `docs/DEPENDENCIES.md`, `docs/TESTING.md`, and the rest

Read `prompt.md` before touching the repo. This project is operated through an agent,
and the agent has written its own instruction manual. It expects to be read first.