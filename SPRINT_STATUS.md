# Sprint Status

Live handoff tracker. The agent reads this at session start to resume exactly where work stopped, and writes
it at session end (same commit as the work or a `chore(status):` commit).

> Baseline: docs + operating prompt only, no code yet. Repo initialized 2026-09-12.
> Current sprint: **Sprint 0 — Foundation** (status: pending).
> Next action: scaffold with `uv` (pyproject, ruff, pytest), implement `config/` schema + `project/` IO +
> `util/` logging/ffmpeg runner, `verify-env`, CI (archlinux), and L0 serialization/config tests per
> SPRINT_PLANNING.md §Sprint 0.

## Milestone

- Target: **M0 (MVP)** — success criteria in PRD §8. Detailed work order in SPRINT_PLANNING.md.

## Sprint table

| # | Name | Status | Notes |
|---|------|--------|-------|
| 0 | Foundation | pending | uv scaffold, config schema, project/ IO, CI, verify-env |
| 1 | Ingestion | pending | ffprobe metadata, validation, stdin |
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

- _none yet_

## Known risks / watch items

- Verify pydantic ≥ 2.9 supports Python 3.14 during Sprint 0 (SPRINT_PLANNING.md risk row).
- Decide during Sprint 3 whether fixture transcripts are static JSON or `espeak-ng`-generated audio
  (DECISIONS.md Open Question 3).
- Confirm whether Sprint 4's minimal scene detection lives in `segment/` or as a `visual/` module
  (DECISIONS.md Open Question 2).

## Agent reminder

End of every session: update this file + commit. Report in chat: sprint, what changed, DoD status, next action.