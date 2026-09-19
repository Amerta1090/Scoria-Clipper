# CLI Spec

Binary: `clipper` (installed via `uv tool install scoria` or `pipx`). All subcommands share:

- persistent, structured logging to `stderr` (json-lines `… --log-level debug`)
- project dir concept: `analysis.json` / `candidates.json` / `ranking.json` are the state handoffs
- `--config` (YAML) merging: `defaults < profile < CLI` (last wins)
- exit codes: `0` ok, `1` pipeline error, `2` config/usage error

## 1. Commands

### `clipper <video> [OPTIONS]` (alias `clipper run`)
One-shot: `analyze` → `segment` → `score` → `rank` → `reframe` → `render` → `report`.
Shortcut for the explicit pipeline; never a different code path that could drift from the steps
(`run` calls the same library entry points as the stage commands). Caption sidecars are built by the
render step (`captions/`), previews + `report.html` by the report step.

Two cut modes: default is the center 9:16 crop; `-p/--profile gaming` (or `reframe.mode: gamer`
in config) selects the two-zone gamer layout — gameplay zone (top, center-anchored crop) +
facecam PiP zone (bottom, configured region), vstack composited (Sprint 12). Profiles may
override non-scoring sections including reframe (CONFIGURATION §2).

The transcript stage needs no whisper binary when the config sets `transcript.path`
(ADR-021): it loads + contract-validates a saved `transcript-info` document instead of
running STT, so captions/scoring work fully offline and CI-safe. Example:

```yaml
# run.yaml
transcript:
  path: analysis/transcript.json   # a saved transcript-info document
```

```bash
clipper run video.mp4 -c run.yaml   # offline transcript from the doc
```

```
Options:
  -o, --output <dir>       project dir  (default: <video>.scoria/)
  -c, --config <file>      YAML config
  -p, --profile <name>     podcast|gaming|lecture|interview|talking-head
  -t, --top <n>            number of clips to render (default 3)
  --no-transcript          skip STT (audio-only scoring fallback)
  --no-visual              skip frame pass
  --no-captions            skip captions entirely (no sidecars, no burn)
  --vertical / --no-vertical   force 9:16 output (default: vertical; --no-vertical is
                           post-MVP and exits 2 — MVP output is always center-reframed 9:16)
  --reframe center         (faces/target = post-MVP; MVP accepts only center and gamer)
  --keep-temp              do not delete analysis temporaries
  --overwrite              overwrite existing project dir
  --log-level <level>      debug|info|warning|error (default info)
  --json                   machine-readable single JSON summary on stdout
```

### `clipper analyze <video>`
Produces `analysis.json` (media + audio + visual + transcript features). Flags: same config/transcript/
visual/overwrite flags, including `--no-transcript` (skips STT → `transcript: null` + `degraded: ["transcript"]`)
and `--json`. This is the only stage that touches the video/audio/frames; everything after it is
pure data.

### `clipper segment <analysis.json>`
Produces `candidates.json` (raw candidate windows + boundary alignment; no scores).

### `clipper score <candidates.json>`
Produces the enriched `candidates.json` (adds per-candidate `ScoreBreakdown`). Deterministic function of
candidates.json + config only.

### `clipper rank <candidates.json> [--top N]`
Produces `ranking.json` (selected top-N + all marginal-gain decisions). Uses SCORING_ENGINE §7.

### `clipper render <ranking.json> [--output <dir>]`
Renders selected clips → `clips/`, captions → `captions/`; no analysis re-run. Flags: `--captions on|off`,
`--reframe`, `--no-burn`, `--crf`, `--preset`, `--force` (re-render even if present).

### `clipper captions <ranking.json>`
Writes SRT + ASS sidecars (`captions/<clip-id>.srt|.ass`, word-karaoke `\k`) plus `captions/captions.json`
(blocks + word timestamps); useful for editing before render. Exit 1 when ranking.json/transcript is missing,
exit 2 on config error (readability rule, ADR-018).

### `clipper reframe <analysis.json>`
Computes the 9:16 reframe plan (crop / scale / blur-pad geometry, even-dim + chroma-aligned) from the
`media` section and writes `reframe.json` (schema `reframe`, `reframe_version center.v1`); the render stage
turns it into the ffmpeg filter graph. Deterministic by construction: the plan is a closed-form function of
media dims + `reframe` config (Sprint 8). Exit 1 when the input isn't an analysis document, has no media
section, or `reframe.mode` isn't `center` (faces/target are post-MVP); exit 2 on config error.

### `clipper explain <project|ranking.json> <clip-id> [--format text|json|yaml] [--json]`
Prints the full `ScoreBreakdown` for one clip and, when a ranking decision is available, the marginal-gain
notes for both chosen and rejected candidates. `--json` is shorthand for `--format json` and dumps the raw
breakdown (byte-identical to the candidate's embedded `score`); `--format yaml` emits the same document as
YAML. Reads the sibling `candidates.json` for the embedded breakdown — no analysis rerun.

### `clipper report <project|analysis.json>`
Writes `previews/` (id-keyed `<clip>.png` still at the clip mid, `<clip>.sheet.png` contact sheet,
`timeline.svg`) + `previews.json` + a self-contained `report.html` from existing JSON artifacts (no
analysis). Clip timings come from `ranking.json`; images embed as base64 unless `report.embed_images: false`.

### `clipper preview <project|analysis.json>`
Alias for `report` limited to preview assets + timeline strip (no `report.html`).

### `clipper config`
- `clipper config show` — active config (default+profile+CLI merged) as YAML.
- `clipper config validate <file>` — validate a YAML config against the schema; exit 2 on error.
- `clipper config write-defaults` — dump the full default config with comments into a file.

### `clipper verify-env`
Runs a self-check: ffmpeg/ffprobe presence + version, whisper binary presence, libass (subtitles filter)
availability, model file presence/checksum. When the active config sets `transcript.path`, it also validates
that saved `transcript-info` document and reports a `transcript_file` tool row — the offline route needs no
whisper binary or model. Zero network. Useful in scripts and for onboarding.

### `clipper fetch-model [--output <path>]`
One-time network op: downloads the configured `transcript.model` from HuggingFace into `model/`,
prints the file's sha256, and reminds you to set `transcript.model_sha256`. `--output` overrides the
download target. Exits with a useful hint if the network is unavailable.

## 2. Examples

```bash
clipper recording.mp4 --top 5                          # done in one shot
clipper recording.mp4 --top 5 -p podcast               # podcast weights
clipper analyze recording.mp4 -o proj                  # inspect, tune config, then:
clipper score  proj/candidates.json -c tuned.yaml
clipper rank   proj/candidates.json -c tuned.yaml --top 5
clipper explain proj c0001
clipper render proj/ranking.json -o proj/clips
clipper report proj
clipper run video.mp4 -c offline.yaml --no-visual      # transcript.path → captions, no whisper/network
```

## 3. STDIN / scripting notes

- `clipper analyze -` reads media from stdin (ffprobe/ffmpeg support pipes); project dir still required.
- All stage commands accept `--json` summaries sized for `jq`:
  `clipper rank proj/candidates.json --top 5 --json | jq '.clips[].id'`.
- Namespace rules: `cNNNN` ids (candidate ids, e.g. `c0001`) are stable across runs for the same
  analysis.json (deterministic ordering), so scripts can reference ids across invocations.

## 4. Error behavior

- Unknown flags / bad config → exit 2 with a pointed message (`clipper config validate` for full dump).
- Missing dependency (e.g. STT binary but transcript requested) → exit 1, message includes
  `clipper verify-env` hint. Analysis continues in degraded modes only when the *flag* allows it, never
  silently — every degraded path is logged at `warning` and stamped in `manifest.json` (`degraded: [...]`).
- Unsupported container / no video stream → exit 1 with ffprobe detail.

## 5. Determinism guarantee for CLI

Same command line + same config file + same local tools + same input → identical artifact bytes and identical
streams. CLI flag conversion to config is mechanical (no hidden state); `manifest.json` records the exact
invocation so drift is always diagnosable.