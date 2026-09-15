# Sprint Status

Live handoff tracker. The agent reads this at session start to resume exactly where work stopped, and writes
it at session end (same commit as the work or a `chore(status):` commit).

> Baseline: docs + operating prompt only, no code yet. Repo initialized 2026-09-12.
> Last sprint: **Sprint 4 — Segmentation + candidates** (status: **done**, this commit).
> Current sprint: **Sprint 5 — Scoring engine** (status: pending).
> Next action (Sprint 5): `score/` module — SCORING_ENGINE.md exact implementation: per-candidate
> feature slices (already embedded in candidates.json), sub-scores in [0,1] with config weights
> normalized to 1 across enabled terms, penalties (edge_silence → flub), ScoreBreakdown with
> function ids, SCORING_VERSION stamping; `visual_activity` term stays a config-weight no-op until
> the motion pass lands (ADR-015).
> Sprint 4 landed: `visual/` module — ffmpeg `scdet` INFO-line scene changes (`resolves DECISIONS.md
> OQ2`, ADR-015; `scene_detection_threshold` [0,1] → scdet %×100, single gray 4fps 64×36 pass with
> `trim` preserving absolute timestamps, degradable `--no-visual`); `segment/` module — boundary
> builder (union of sentence/silence/scene, 50 ms dedupe, canonical source order) + window generator
> (A = nearest preferred-band boundary, B = last-before-max with `hard_cut_margin`, hard-cut fallback,
> ≤ max_candidates_per_start, duplicate-window drop, ADR-016) → raw `candidates.json` (schema
> `candidates`, slices half-open/inclusive per source, compact audio window range); wired into
> `analyze_video` (`analysis.json.visual` + degraded) + `clipper segment` CLI; fixture
> `analysis_small.json` (14-candidate golden) + `test_segment.py`/`test_visual.py`; `segment_from_whisper`
> now actually gates whisper segment hints (S3 drift reconciled); 137 tests + 1 skip green, ruff clean,
> end-to-end analyze+segment smoke OK.

## Milestone

- Target: **M0 (MVP)** — success criteria in PRD §8. Detailed work order in SPRINT_PLANNING.md.

## Sprint table

| # | Name | Status | Notes |
|---|------|--------|-------|
| 0 | Foundation | **done** | uv scaffold, config schema, project/ IO, CI, verify-env |
| 1 | Ingestion | **done** | ffprobe metadata, validation, stdin (analysis.json.media) |
| 2 | Audio analysis | **done** | PCM pass, energy/RMS/silence/loudness/peaks (analysis.json.audio) |
| 3 | Transcript pipeline | **done** | whisper bridge + grouping, deferred OQ3 (ADRs 013, 014) |
| 4 | Segmentation + candidates | **done** | visual/ scdet scenes + segment/ boundaries+windows (ADRs 015, 016) |
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
- Sprint 2: `scoria/audio/pipeline.py` annotates `media: MediaInfo` but imports it **only under
  `TYPE_CHECKING`** — the eager import created a real circular chain (`ingest/__init__` → `ingest/pipeline`
  → `audio/pipeline` → `ingest.models` → `ingest/__init__` partial). Annotations are strings under
  `from __future__ import annotations`, so type-only import keeps the stage signature `analyze_audio(path, cfg, media)`
  without a runtime edge into `ingest`. Not an ADR (implementation detail, no stated rule overturned).
- Sprint 2: ebur128 `I:`/`Peak:` parsed from the **Summary: block only** — the per-window progress lines
  emit the same `I: … LUFS` pattern (e.g. `-70.0` during leading silence) and would shadow the final
  integrated reading in a whole-stderr regex search.
- Sprint 3: whisper.cpp ≥ 1.9 dropped the documented `words[]`/`t0,t1` JSON; word timestamps now live
  only in per-token `t_dtw` (centiseconds) and require `-nfa --dtw <preset> -ojf` (ADR-013). Segment
  offsets in this build are garbage; parser uses tokens only. Greedy needs `-bs 0` (default is beam 5).
- Sprint 3: `segment_from_whisper` config key exists as schema but the bridge reads whisper segment
  boundaries implicitly via `segment_end_indices`; the flag is unused by MVP grouping (segments are
  always the hint, per ADR-013 design) — **reconciled in Sprint 4: the flag now really gates the hints
  (`segment_from_whisper: false` → `segment_end_indices=()`); two new tests lock it in.**
- Sprint 3: during development whisper-cli lived off-PATH at `/tmp/…/whisper.cpp/build/bin/whisper-cli`,
  so all real e2e used an absolute `transcript.binary` (supported: path-with-separator). The 488 MB
  `model/ggml-small.bin` stays untracked (.gitignore); its sha is pinned in DEPENDENCIES.md/ADR-013.
- Sprint 3: fixtures are static JSON (ADR-014) — no speech audio in CI; a real-bridge smoke test is
  env-gated (`SCORIA_WHISPER_BIN` + `SCORIA_WHISPER_MODEL`) and skipped by default.
- Sprint 4: the `analysis_small.json` golden yields **14** candidates, not the 10 in the original S4
  plan — the window generator also emits for starts at sentence starts 4 s and 12 s, and band-A can
  pick a longer/two windows later in the video (durations ≥ pref when the timeframe allows).
- Sprint 4: scdet emits **percentage-scale** scores and the config's `[0,1]` threshold is scaled ×100 —
  a "0.35" config is scdet `threshold=35`. A testsrc2→smptebars test cut scored only ~31 (below the
  0.35 config) so the visual fixture uses black→white (score 99.609 at t=2.0).

## Known risks / watch items

- **Resolved (Sprint 0):** pydantic 2.13.5, numpy 2.5.3, typer 0.27.2, pyyaml 6.0.3, rich 15.0.0 all verified
  on Python 3.14.7 via `uv sync` + tests.
- **Resolved (Sprint 1):** ffprobe n9.0.1 JSON probing verified on generated 16:9 / 9:16 / 4:3 / audio-only
  fixtures; duration/AR/timebase exact; VFR `avg_frame_rate` (e.g. `0/0`) recorded raw, timestamps normalized
  to seconds. Confirmed ffprobe builds diverge on CLI flags (`-nostdin` rejected) → see drift note.
- Decide during Sprint 3 whether fixture transcripts are static JSON or `espeak-ng`-generated audio
  (DECISIONS.md Open Question 3). **Resolved Sprint 3: static JSON primary (ADR-014).**
- Confirm whether Sprint 4's minimal scene detection lives in `segment/` or as a `visual/` module
  (DECISIONS.md Open Question 2). **Resolved Sprint 4: `visual/` module, scdet-only, motion deferred (ADR-015).**
- Real-video sanity runs (STT latency, real boundary/cut quality, PRD §8 cold-start) use untracked captures
  in `sample raw/` (git-ignored; e.g. a live-streaming gamer video) — manual, never CI (TESTING.md §2.1).

## Agent reminder

End of every session: update this file + commit. Report in chat: sprint, what changed, DoD status, next action.