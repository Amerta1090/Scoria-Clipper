# Sprint Status

Live handoff tracker. The agent reads this at session start to resume exactly where work stopped, and writes
it at session end (same commit as the work or a `chore(status):` commit).

> Baseline: docs + operating prompt only, no code yet. Repo initialized 2026-09-12.
> Last sprint: **Sprint 1 — Ingestion** (status: **done**).
> Current sprint: **Sprint 2 — Audio analysis** (status: pending).
> Next action (Sprint 2): `audio/` module — PCM extraction via ffmpeg f32le mono 16k, numpy
> window RMS/energy/silence, ebur128 integrated loudness, `analysis.json.audio`.
> Sprint 1 landed: `ingest/` module (`analysis.json.media` contract: stream/duration/AR/timebase
> normalized to seconds, rotation-aware AR, analysis window), stdin support (spools to project
> tmp, needs `-o`), actionable MediaError hints, `clipper analyze` + manifest stamping,
> project-dir/overwrite semantics, L1/L5 tests (75 green).

## Milestone

- Target: **M0 (MVP)** — success criteria in PRD §8. Detailed work order in SPRINT_PLANNING.md.

## Sprint table

| # | Name | Status | Notes |
|---|------|--------|-------|
| 0 | Foundation | **done** | uv scaffold, config schema, project/ IO, CI, verify-env |
| 1 | Ingestion | **done** | ffprobe metadata, validation, stdin (analysis.json.media) |
| 2 | Audio analysis | pending | PCM pass, energy/RMS/silence/loudness |
| 3 | Transcript pipeline | pending | whisper.cpp bridge, sentence grouping, degraded path |
| 4 | Segmentation + candidates | pending | boundary builder, window generator (needs scene list) |
| 5 | Scoring engine | pending | SCORING_ENGINE.md exact implementation |
| 6 | Ranking + diversity | pending | greedy marginal-gain with overlap/sim/gap |
| 7 | Captions | pending | SRT/ASS + karaoke + line builder |
| 8 | Vertical reframing | pending | center crop + blur-pad geometry |
| 9 | FFmpeg rendering | pending | filter graph, static gain, burn-in, atomic output |
| 10 | Preview/report/explain | pending | thumbnails, contact sheet, report.html, explain renderers |
| 11 | Integration hardening | pending | one-shot `run`, L4 determinism, degraded matrix, README, packaging |

## Control of work

- Only **one** sprint `in_progress` at a time. Flip status only when its DoD (SPRINT_PLANNING.md + prompt.md) passes.
- Each flip = a commit; SPRINT_STATUS updated in the same change.

## Drift / deviations

_(Append here anything that diverges from SPRINT_PLANNING.md, with the reason. Structural overturns must also
get a DECISIONS.md ADR.)_

- Sprint 0: caption-readability rule (CONFIGURATION.md §3, `captions.max_duration ≥
  (chars_per_line·max_lines)/(wpm/60)`) is **not** implemented in the config schema — the defaults
  (`max_duration: 4.5`) contradict it, and it is conceptually Sprint 7 (captions) territory. Deferred to
  Sprint 7; tracked as DECISIONS.md Open Question 4 (ADR required on adoption).
- Sprint 0: dev tooling moved from `[project.optional-dependencies].dev` to PEP 735 `[dependency-groups] dev`
  (ADR-012) — `uv` would otherwise not install it by default, breaking `uv sync && pytest`.
- Sprint 1: `run_ffprobe` drops `-nostdin` — the ffprobe build on this machine (n9.0.1) rejects it
  (`Option not found`), and ffprobe only reads stdin when given `-` as input, which ingest never does
  (it always probes a spooled file). Pinned args stay fixed + deterministic. ARCHITECTURE.md §3 updated
  to match; not an ADR (no documented decision overturned).

## Known risks / watch items

- **Resolved (Sprint 0):** pydantic 2.13.5, numpy 2.5.3, typer 0.27.2, pyyaml 6.0.3, rich 15.0.0 all verified
  on Python 3.14.7 via `uv sync` + tests.
- **Resolved (Sprint 1):** ffprobe n9.0.1 JSON probing verified on generated 16:9 / 9:16 / 4:3 / audio-only
  fixtures; duration/AR/timebase exact; VFR `avg_frame_rate` (e.g. `0/0`) recorded raw, timestamps normalized
  to seconds. Confirmed ffprobe builds diverge on CLI flags (`-nostdin` rejected) → see drift note.
- Decide during Sprint 3 whether fixture transcripts are static JSON or `espeak-ng`-generated audio
  (DECISIONS.md Open Question 3).
- Confirm whether Sprint 4's minimal scene detection lives in `segment/` or as a `visual/` module
  (DECISIONS.md Open Question 2).

## Agent reminder

End of every session: update this file + commit. Report in chat: sprint, what changed, DoD status, next action.