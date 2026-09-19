# Roadmap

Milestones for `scoria`/`clipper`. Detailed sprint breakdown in SPRINT_PLANNING.md; this is the big picture
and its guardrails.

## Milestone M0 — "Clips land on boundaries" (MVP)

Sprints 0–11. Produces the PRD §8 success criteria: one command from talking-head video → 3 clean
1080×1920 clips with burned captions, byte-deterministic artifacts, `explain` everywhere.

**Exit criteria**
- `clipper v.mp4 --top 3` works on a 6-min talking-head fixture.
- ≥ 90 % clean cuts on fixture media; determinism test green; CI green.

## Milestone M1 — "Look and act right"

- **Face-based reframing** (detect → centroid → EMA/One-Euro smoothed focus → clamp) behind the existing
  `reframe/` interface; `--reframe faces`.
- **Gamer two-zone reframe** (`reframe.mode: gamer`): deterministic split layout — gameplay zone
  (center-anchored crop) on top, facecam PiP zone on bottom, vstack composite (Sprint 12).
  Face-tracking/PiP auto-detect stays `faces` (ML variant, ADR-gated).
- **Offline caption route** (`transcript.path`, Sprint 13, ADR-021): a saved `transcript-info` document
  replaces whisper.cpp entirely — captions + burn provable without STT/network/CI secrets.
- **Two-pass loudnorm** as an opt-in (`audio.method: loudnorm`), documented impact on determinism.
- **faster-whisper engine option** (`transcript.engine: faster-whisper`) for people who want pip-only installs.
- **Music/beat "energy mode"** — spectral features (onset, BPM) added as a `music` profile signal;
  no-whisper profile that scores on audio+visual only with tuned bands.
- Better sentence grouping: punctuation model built from local heuristics + word-confidence heuristics.

## Milestone M2 — "Understand the room"

- Multi-speaker diarization via local clustering of speaker-ish features (vector-cluster whisper segments or
  a small local diarizer). **Exploratory** — explicitly not promised; ship only if quality beats the silences
  approach for real podcasts.
- Topic-distance beyond term-overlap: deterministic **TF-IDF over the corpus** for Jaccard distance
  (still no LLM), or locally-trained embeddings (justified, documented) — only if term-overlap diversity is
  proven insufficient by evaluation.

## Milestone M3 — "Shareable"

- Community profile contributions (packaging `profiles/` git-folder, message schema versioned).
- Optional batch CLI (`clipper batch manifest.yaml`).
- Package to AUR (`scoria`) for Arch users; recording REPROD workflow (official model checksums in
  `model/checksums.json`).

## Guardrails (referenced by all sprints)

- **No AI in scoring** unless there's a written reasoning + evaluation section (route via DECISIONS.md).
- **No cloud** at runtime; `block-network` enforced by CI.
- **Non-goals hold**: no thumbnails/titles/publishing/web/multi-user (PRD §3).
- **PIPELINE stays composeable** — every milestone feature lands behind a config key, never a fork.

## Effort shape (rough, personal project)

M0 ≈ 6–8 focused evenings + 1 integration day (STT + render the risky bits).
M1 ≈ 3–4 evenings. M2 exploratory, re-scoped after real media evaluation. M3 packaging/as-needed.