# Sprint Status

Live handoff tracker. The agent reads this at session start to resume exactly where work stopped, and writes
it at session end (same commit as the work or a `chore(status):` commit).

> Baseline: docs + operating prompt only, no code yet. Repo initialized 2026-09-12.
> Last sprint: **Sprint 3 — Transcript pipeline** (status: **done**, this commit).
> Current sprint: **Sprint 4 — Segmentation + candidates** (status: pending).
> Next action (Sprint 4): boundary builder + window generator — sentence starts/ends from
> `analysis.json.transcript`, silence intervals from audio, scene changes from visual; degenerate
> to silence+scene when `transcript: null` (resolves DECISIONS.md Open Question 2).
> Sprint 3 landed: `transcript/` module — whisper.cpp 1.9.4 bridge pinned to `-bs 0 -nt -np -sow
> -nfa -dtw <preset> -ojf` (flash-attn off + DTW or there are no timestamps), words rebuilt from
> per-token `t_dtw` centisecond BPE tokens (no `words[]` in ≥ 1.9 JSON, ADR-013), monotonic snap +
> sentence grouping (gap ≥ 1.2 s, whisper segment end + gap ≥ 0.30 s, < 2 words merge back) with
> `?`/`.` inference from en+id question starters, degraded path `transcript: null` only via flag;
> wired into `analyze_video` (3-tuple) + `analysis.json.transcript` + manifest `whisper-cli`/
> `whisper-model` stamps; CLI: analyze `--no-transcript`, `fetch-model`, verify-env whisper version +
> model checksum; golden fixture `transcript_small.json` (ADR-014) + `test_transcript.py` (20 tests;
> 116 total green); real bridge e2e validated live on `ggml-small.bin` via an absolute binary path
> (`201028 < 44.7 s`-class run, words+sentences produced).

## Milestone

- Target: **M0 (MVP)** — success criteria in PRD §8. Detailed work order in SPRINT_PLANNING.md.

## Sprint table

| # | Name | Status | Notes |
|---|------|--------|-------|
| 0 | Foundation | **done** | uv scaffold, config schema, project/ IO, CI, verify-env |
| 1 | Ingestion | **done** | ffprobe metadata, validation, stdin (analysis.json.media) |
| 2 | Audio analysis | **done** | PCM pass, energy/RMS/silence/loudness/peaks (analysis.json.audio) |
| 3 | Transcript pipeline | **done** | whisper bridge + grouping, deferred OQ3 (ADRs 013, 014) |
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
  always the hint, per ADR-013 design) — reconcile/remove in Sprint 4 align step.
- Sprint 3: during development whisper-cli lived off-PATH at `/tmp/…/whisper.cpp/build/bin/whisper-cli`,
  so all real e2e used an absolute `transcript.binary` (supported: path-with-separator). The 488 MB
  `model/ggml-small.bin` stays untracked (.gitignore); its sha is pinned in DEPENDENCIES.md/ADR-013.
- Sprint 3: fixtures are static JSON (ADR-014) — no speech audio in CI; a real-bridge smoke test is
  env-gated (`SCORIA_WHISPER_BIN` + `SCORIA_WHISPER_MODEL`) and skipped by default.

## Known risks / watch items

- **Resolved (Sprint 0):** pydantic 2.13.5, numpy 2.5.3, typer 0.27.2, pyyaml 6.0.3, rich 15.0.0 all verified
  on Python 3.14.7 via `uv sync` + tests.
- **Resolved (Sprint 1):** ffprobe n9.0.1 JSON probing verified on generated 16:9 / 9:16 / 4:3 / audio-only
  fixtures; duration/AR/timebase exact; VFR `avg_frame_rate` (e.g. `0/0`) recorded raw, timestamps normalized
  to seconds. Confirmed ffprobe builds diverge on CLI flags (`-nostdin` rejected) → see drift note.
- Decide during Sprint 3 whether fixture transcripts are static JSON or `espeak-ng`-generated audio
  (DECISIONS.md Open Question 3). **Resolved Sprint 3: static JSON primary (ADR-014).**
- Confirm whether Sprint 4's minimal scene detection lives in `segment/` or as a `visual/` module
  (DECISIONS.md Open Question 2).
- Real-video sanity runs (STT latency, real boundary/cut quality, PRD §8 cold-start) use untracked captures
  in `sample raw/` (git-ignored; e.g. a live-streaming gamer video) — manual, never CI (TESTING.md §2.1).

## Agent reminder

End of every session: update this file + commit. Report in chat: sprint, what changed, DoD status, next action.