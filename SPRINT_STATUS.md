# Sprint Status

Live handoff tracker. The agent reads this at session start to resume exactly where work stopped, and writes
it at session end (same commit as the work or a `chore(status):` commit).

> Baseline: docs + operating prompt only, no code yet. Repo initialized 2026-09-12.
> Last sprint: **Sprint 8 — Vertical reframing** (status: **done**, this commit).
> Current sprint: **Sprint 9 — FFmpeg rendering** (status: pending).
> Next action (Sprint 9): `render/` module — ffmpeg filter graph builder from ranking.json + reframe.json,
> trim/crop/scale/subs/loudness/encode, atomic output (SPRINT_PLANNING.md §S9; reframe.json is the crop plan).
> Sprint 8 landed: `reframe/` module — pure closed-form geometry: `plan_for_dims(source_w, source_h, cfg)` /
> `build_reframe_plan(media, cfg)` → `ReframePlan` doc (schema "reframe", REFRAME_VERSION 1,
> reframe_version "center.v1"); `strategy_for` scales/center-crops/blur-pads by AR (9:16 exact → scale;
> 9:16 < ar ≤ `blurbad_threshold` → center crop; ar > threshold or ar < 9:16 → blur-pad); `compute_crop`
> even-dim + even-offset center window (banker's ties-to-even), `compute_blur_pad` contain-dims + even bars;
> `clipper reframe` writes `reframe.json` (post-MVP mode guard: faces/target → exit 1). Tests: 20 new —
> geometry table (16:9, 4:3, 1:1, 9:16, 21:9, taller-than-9:16) exact, rounding rules, determinism, CLI
> (write/json/guard/errors), two L3 ffprobe dims checks on rendered testsrc2 (crop path + blur-pad overlay).
> 263 tests + 1 skip green (was 243+1), reframe/ at 100 % line coverage, ruff clean.

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
| 6 | Ranking + diversity | **done** | greedy marginal-gain with overlap/sim/gap, `clipper rank`, ADR-017, this commit |
| 7 | Captions | **done** | captions/ module: lines + SRT/ASS + \k karaoke + readability (ADR-018), `clipper captions`, this commit |
| 8 | Vertical reframing | **done** | reframe/ module: AR→even-dim geometry, center crop + blur-pad, `clipper reframe`, L3 dims, this commit |
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
  Sprint 7; tracked as DECISIONS.md Open Question 4 (ADR required on adoption). **Resolved Sprint 7: ADR-018.**
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
- Sprint 6: SCORING_ENGINE.md §7's penalties were ambiguous as dimensionless λ; pinned by ADR-017 as
  **0–100 score-units × λ-ratio** (not a normalized 0–1 total) because the normalized reading would leave a
  fully-overlapping equal-score sibling at ~99 % of its value and break the "never 3 picks from the same
  minute" AC — margin/tie-breaks must compare directly against the 0–100 totals.
- Sprint 6: `_build_rejected` needs no best-gain scan — marginal gains are monotonically non-increasing per
  candidate (penalties only grow as `chosen` grows), so a rejected clip's best gain is always its step-1
  pre-choice gain; this also removed the "never had a marginal gain" rejected reason, which was unreachable
  (step 1 evaluates every candidate before any choice exists, so everyone has a history entry).
- Sprint 7: the AC "every caption ≤ max_duration" has a documented exception (ADR-018): a **single word**
  longer than `max_duration` stays whole (words are never split or dropped). Multi-word blocks always respect
  the bound; the fixture `analysis_small.json` happens to contain 6–20 s single words, so its caption blocks
  are all single-word. The AC's "fixtures byte-match golden files" is satisfied by inline golden SRT/ASS
  strings (same static-fixture strategy as ADR-014, no new binary fixtures).
- Sprint 7: sidecar files are **id-keyed** (`captions/c0006.srt|.ass`), not the `clip-01.*` naming sketched in
  ARCHITECTURE.md §6 — clip `id` is the stable rank-independent identity; ARCHITECTURE.md updated. Render (S9)
  will decide final clip filename naming; `captions.json` carries both id and rank for the mapping.
- Sprint 7: the readability rule's literal formula was unusable (see ADR-018) — adopted as
  `(chars_per_line·max_lines/5)/(wpm/60)` with 5 chars ≈ 1 word and new `captions.wpm` (default 200);
  `max_duration` default 4.5 → 5.1. `tests/fixtures/config_good.yaml` bumped `max_duration` 4.5 → 5.0 to stay
  valid under its 40×2 chars (min 4.8).
- Sprint 8: the plan is **video-wide** (one `reframe.json` for the whole source) — per-clip variation only
  becomes possible with focus modes (`faces`/`target`, post-MVP). The post-MVP guard lives in the CLI
  (`clipper reframe` exits 1 for non-center), not in `build_reframe_plan` (the interface accepts any mode).
- Sprint 8: ARCHITECTURE.md §9 ("portrait narrower than 9:16 → blur-pad") and CONFIGURATION.md
  (`blurbad_threshold: 1.78 → blur-pad for very-wide`) both hold — `strategy_for` blur-pads on **either**
  side: ar < 9/16 (horizontal bars) or ar > threshold (vertical bars). 16:9 (1.7778) is the widest crop case.
- Sprint 8: even-dim rounding uses **banker's ties-to-even** (`round_even(v) = 2·round(v/2)`): e.g. 607.5 →
  608, 202.5 → 202, 219 → 220 offset. Center-crop offsets can never overflow the source by construction, so
  only the width clamp (for out-of-contract inputs) is kept — the offset guard was provably dead and removed.
- Sprint 8: the DoD's "L3 ffprobe check on rendered fixture" is stubbed: render (S9) owns the filter graph, so
  the two L3 tests build a Sprint-9-shaped graph (crop→scale, and blur-pad contain+boxblur+overlay) from the
  plan's own numbers and assert exact 1080×1920 via ffprobe. Rewire to the real graph builder when S9 lands.
- Sprint 8: this ffmpeg (9.0.1) overlay filter rejects the `format=yuv420p` option (`Invalid argument`) — the
  L3 blur-pad graph omits it (overlay defaults are yuv420p-compatible for these inputs); render (S9) must not
  pass `format=yuv420p` to overlay on this build.

## Known risks / watch items

- **Resolved (Sprint 0):** pydantic 2.13.5, numpy 2.5.3, typer 0.27.2, pyyaml 6.0.3, rich 15.0.0 all verified
  on Python 3.14.7 via `uv sync` + tests.
- **Resolved (Sprint 1):** ffprobe n9.0.1 JSON probing verified on generated 16:9 / 9:16 / 4:3 / audio-only
  fixtures; duration/AR/timebase exact; VFR `avg_frame_rate` (e.g. `0/0`) recorded raw, timestamps normalized
  to seconds. Confirmed ffprobe builds diverge on CLI flags (`-nostdin` rejected) → see drift note.
- Sprint 8+ watch: ASS burn-in needs libass (`subtitles` filter) at render time — captions are already
  libass-shaped (V4+ styles, `Alignment 2` bottom-center, `margin_v` safe-area), and burn must degrade
  gracefully to sidecar-only when libass is missing (Sprint 9 degraded path).
- Real-video sanity runs (STT latency, real boundary/cut quality, PRD §8 cold-start) use untracked captures
  in `sample raw/` (git-ignored; e.g. a live-streaming gamer video) — manual, never CI (TESTING.md §2.1).

## Agent reminder

End of every session: update this file + commit. Report in chat: sprint, what changed, DoD status, next action.