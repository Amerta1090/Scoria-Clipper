# Changelog

All notable changes, aggregated per milestone. Format follows keep-a-changelog;
versions stay `0.x` until M0 ships (`clipper v.mp4 --top 3` on a real 6-min capture,
PRD §8).

## [Unreleased]

### Sprint 13 — Captions-actual

- **Added** offline transcript ingest (`transcript.path`, ADR-021): point the config at a
  saved `transcript-info` JSON document and the transcript stage loads + contract-validates
  it instead of running whisper.cpp — deterministic, no STT binary, no network, CI-safe.
  Broken documents are a hard error (exit 1), never a silent skip.
- **Added** `manifest.json.transcript_source` (file | whisper.cpp | null) stamping how this
  run's transcript was produced; `clipper verify-env` gains a `transcript_file` row that
  validates the configured document.
- **Added** captions-on L4 determinism in the default suite: two transcript.path-fed runs →
  byte-identical corpus incl. SRT/ASS sidecars + clip streams; burn-smoke asserts
  `render.json.burn=True` when libass is present (else `burn_sidecar_only`).

### Sprint 12 — Gamer two-zone reframe

- **Added** `-p/--profile gaming` → `reframe.mode: gamer`: two-zone vertical stack
  (gameplay cover-fit top + facecam PiP bottom) composited with `split`+`vstack`
  (`setsar=1` square pixels), `reframe.json` plan v2 (`layout` + `zones`, ADR-022).
- **Added** `reframe.gamer` config section (`v_fraction`, facecam `region`) with validation;
  default `clipper run` stays center crop (regression-tested).

## [0.1.0] - 2026-09-18

### Sprint 11 — Integration hardening

- **Added** real one-shot pipeline: `clipper run` now drives
  analyze → segment → score → rank → reframe → render → report through the same
  library entry points as the stage commands (no parallel code path that could
  drift); `--json` emits a full summary (paths, selected/rendered counts, degraded).
- **Added** L4 cross-stage determinism test: two full `clipper run`s on the same
  input + config produce a byte-identical JSON corpus and byte-identical clip streams.
- **Added** degraded-mode matrix tests covering `--no-transcript`, `--no-visual`, and
  `--no-captions` (never crashes, never silent — `manifest.json.degraded` is stamped).
- **Fixed** `run` flag mapping: `--top`, `--no-visual`, and `--no-captions` now reach
  the pipeline (`--no-captions` disables sidecars + burn); `--no-vertical` exits 2 with
  a pointed message (post-MVP; MVP output is always 9:16 center reframe).
- **Added** README quickstart, this CHANGELOG, a docs link-check test, and
  AUR-ready packaging metadata (license, classifiers, project URLs).
- **Docs** `CLI_SPEC.md` reconciled with reality (removed unimplemented
  `--seed-stages`; `--no-captions`/`--no-vertical` semantics; `cNNNN` id namespace).

### Sprints 0–10 (foundation → preview/report/explain)

Repository foundation (uv scaffold, config schema, project IO, CI, verify-env);
ingestion (ffprobe metadata + validation); audio analysis (energy/RMS/silence/loudness/
peaks); transcript pipeline (whisper.cpp bridge + sentence grouping); segmentation +
candidates (visual scdet scenes + boundary/window generator); scoring engine
(`clipper score`, golden totals pinned); ranking + diversity (greedy marginal-gain);
captions (line builder + SRT/ASS + karaoke + readability); vertical reframing (center
crop + blur-pad); ffmpeg rendering (keyed-clip graph, atomic mp4, caption burn);
preview/report/explain (stills + contact sheets + SVG timeline + self-contained
report.html). See `SPRINT_STATUS.md` and `docs/DECISIONS.md` for detail.