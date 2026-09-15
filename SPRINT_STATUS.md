# Sprint Status

Live handoff tracker. The agent reads this at session start to resume exactly where work stopped, and writes
it at session end (same commit as the work or a `chore(status):` commit).

> Baseline: docs + operating prompt only, no code yet. Repo initialized 2026-09-12.
> Last sprint: **Sprint 5 — Scoring engine** (status: **done**, this commit).
> Current sprint: **Sprint 6 — Ranking + diversity** (status: pending).
> Next action (Sprint 6): greedy marginal-gain ranking (SCORING_ENGINE.md §7) + diversity constraints — `rank/`
> module, `clipper rank` CLI, `RankingConfig` lens, `ranking.json` contract, CC0 fixture labels (TESTING.md §6).
> Sprint 5 landed: `score/` module — `score_candidates()` first-pass (analysis.json) / re-score (embedded
> inputs) with config-only determinism (CLI_SPEC: score = f(candidates.json, config)); terms
> `audio_energy/speech_density/pacing/hook/completeness/visual_activity(no-op ADR-015)/keyword_density/sentence_quality`
> + penalties `edge_silence/dead_air/mid_sentence_start/mid_word_end/low_energy_tail/flub_repeats/peak_clipping`,
> all capped & total-capped; `ScoreBreakdown` stamps `scoring_version` + `signals_disabled` + `renorm_factor`,
> every term/penalty embeds its inputs; `completeness` added to `TRANSCRIPT_DISABLED_TERMS`; `clipper score`
> CLI (dir or candidates.json, `--json`, exit 1 missing sibling analysis on first pass / exit 2 bad config);
> fixture golden totals pinned to 4 decimals (c0001 64.0449 … c0012 42.8110 mid_sentence, 75.2809 family,
> 32.8090 mid_word family); 192 tests + 1 skip green (was 137+1), ruff clean; re-score byte-identical; bug:
> edge-silence exact-tol float fill missed trailing silence (40.0−39.6 < 0.4) — `_EDGE_EPS` guard.

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
| 5 | Scoring engine | **done** | score/ module + `clipper score`, golden totals pinned, this commit |
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
- Sprint 5: `SCORING_ENGINE.md §2.3`'s `pacing_band.hi` (1.35) and `wpm_base_window` (30) are reserved
  config keys — the trapezoid knots (1.0/1.2/1.5) are spec numerals, not config. Documented at §2.3.
- Sprint 5: the enriched document's floats are serialized under the 4-decimal contract (ADR-010) — the
  pinned golden totals (e.g. c0001 64.0449) are the **normalized** doc values, so a byte-identical re-score
  is guaranteed by construction (inputs are contract-normalized at feature-build time).

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