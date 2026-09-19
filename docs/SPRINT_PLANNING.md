# Sprint Planning

Sprints are sequence by **technical dependency**, not feature list. This ordering matches the pipeline
(ARCHITECTURE §4): later stages consume earlier stages' JSON, so each sprint only compiles against stable,
already-shipped contracts.

Sprint template used below:
`objective · deliverables · dependencies · implementation tasks · tests · acceptance criteria · definition of done · risks`.

Cross-cut everywhere: logging to stderr, error messages with action hints, pydantic contracts, ruff-clean,
no network at runtime, every sprint's artifacts round-trip through the serialization contract in `project/`.

## Sprint 0 — Foundation

- **Objective:** repo, tooling, config schema, project-dir IO, logging, CI wiring. Everything later compiles against it.
- **Deliverables:** pyproject.toml (uv), ruff/pytest config, `scoria/` skeleton package, `config/` models (full CONFIGURATION.md schema), `project/` serialization + manifest, `util/` logging + ffmpeg runner stub, README stub, `verify-env`, CI (archlinux) with network-sandboxed pytest.
- **Dependencies:** none.
- **Tasks:** scaffold; pydantic schema with validation rules; stable-float JSON writer; manifest writer; error taxonomy; `scoria --help` skeleton; CI runner file.
- **Tests:** L0 serialization contract; config validation (unknown key → error; sum-of-weights check); `verify-env` reports versions.
- **Acceptance criteria:** `uv sync && pytest` green; `clipper config validate` round-trips the default config; a throwaway JSON artifact survives two serialize→parse→serialize cycles byte-identically.
- **Definition of done:** repo openable with two documented commands (`uv sync`, `uv run clipper --help`); CI button green.
- **Risks:** tool-version drift between local and CI → pin `uv.lock`; Python 3.14 vs pydantic support (pydantic ≥2.9 supports 3.14; verify in S0).

## Sprint 1 — Ingestion

- **Objective:** read any input sanely and describe it exactly. Feeds everything else.
- **Deliverables:** `ingest/` module; `media.json` inside analysis.json; validation errors with ffprobe detail; stdin support.
- **Dependencies:** S0 (project/contracts).
- **Tasks:** ffprobe wrapper (JSON parse, error mapping); stream selection (`video_stream` config); duration/AR validation; `analyze_start/end` slicing support; VFR frame-time base (use actual `start_time/time_base` from ffprobe).
- **Tests:** ffprobe wrapper on a generated 16:9 + a 9:16 + a 4:3 file; missing/video-less input → exit 1; stdin path.
- **Acceptance criteria:** `analysis.json.media` has exact stream, duration, AR, timebase; bad file errors are actionable.
- **Definition of done:** ingest covered by L1 tests; no silent fallback.
- **Risks:** exotic containers (VFR, odd timebases) → normalize frame timestamps to seconds at ingest, single source of truth.

## Sprint 2 — Audio analysis

- **Objective:** deterministic audio feature layer (RMS/energy/silence/loudness), consumed by scoring and render.
- **Deliverables:** `audio/` module: PCM extraction via ffmpeg (f32le, pinned rate), numpy window RMS/energy, silence list, ebur128 integrated loudness measure, peaks; `analysis.json.audio`.
- **Dependencies:** S0, S1 (timestamps).
- **Tasks:** PCM pass; window math; silence threshold/merge; loudness measure; write audio section; determinism (fixed windows).
- **Tests:** L1 on synthetic fixture with known sine placement → exact silence spans; energy monotonicity checks; staged vs whole-file equal.
- **Acceptance criteria:** audio section byte-stable across two runs; silence spans match planted gaps ±50 ms.
- **Definition of done:** audio feature extraction pure-tested; fast (< realtime on fixture).
- **Risks:** container quirks with `-f f32le` pipe → force `-vn`, `-ac 1`; float32 range normalization documented (PCM f32 scaled to [-1,1]).

## Sprint 3 — Transcript pipeline

- **Objective:** words + sentences with timestamps; degrade cleanly when STT absent.
- **Deliverables:** `transcript/` module: whisper.cpp bridge (deterministic flags), JSON parse, word spans, sentence grouping + punctuation inference, `transcript: null` path; hook/keyword term application downstream-ready.
- **Dependencies:** S0, S1 (timing base).
- **Tasks:** bridge with pinned flags (`greedy`, threads); fixture-driven sentence grouper; punctuation heuristics; STT-missing degradation; model checksum verify; manifest stamping (model sha, STT version).
- **Tests:** grouper against `transcript_small.json` (question opener, mid-sentence trap, pause split); whisper bridge skipped in CI unless binary present (L1 uses fixture JSON); degraded-mode tests.
- **Acceptance criteria:** word/sentence timestamps monotonic; no word overlap; `manifest.degraded` set correctly; two runs with same model → identical transcript JSON.
- **Definition of done:** sentence groups + caption input stable on fixtures; no crash on missing STT.
- **Risks:** punctuation quality (top risk, see PRD §9) → own heuristics + fixture regression; whisper word timestamps overlap tiny gaps → merge/snap rule.

## Sprint 4 — Segmentation + candidates

- **Objective:** produce excellent *windows before scoring* (the "cut hygiene" sprint).
- **Deliverables:** `segment/` module: boundary union (silence ∪ sentence ∪ scene), dedupe/sort, feature slice per candidate, aligned_to flags; `candidates.json` raw.
- **Dependencies:** S2, S3 (silences, sentences), plus a minimal `visual/` scene list (moved here — see note below).
- **Tasks (re-ordered):** port minimal scene detection from the visual milestone into segment inputs (scdet-thresholded scene list); boundary builder; window generator (§ARCHITECTURE 5.4); candidate feature slicing; serialization.
- **Tests:** L0 golden: known boundaries → exact candidate list; durations within [min,max]; complete-cut flags correct; hard-cut case; O(boundaries) bound. Real-video sanity (manual, optional): run against a capture from `sample raw/` (untracked) to eyeball whether real sentences/silences/scenes trigger sensible candidates.
- **Acceptance criteria:** candidate list equals fixture golden; every candidate carries aligned_to + durations; ≥1 candidate per video of the fixture.
- **Definition of done:** segmentation pure-tested without media tools (synthetic silences/sentences/scenes in JSON).
- **Risks:** boundary density explosion → cap + deterministic selection; sentence-only boundaries on `--no-transcript` → silence+scene path tested.

## Sprint 5 — Scoring engine

- **Objective:** implement SCORING_ENGINE.md exactly: normalized sub-scores, weights, penalties, breakdowns, renormalization.
- **Deliverables:** `score/` module with pure functions per term; ScoreBreakdown builder; config-driven weights; SCORING_VERSION stamping; `explain` data completeness.
- **Dependencies:** S4 (feature slices), S0 config.
- **Tasks:** implement each term (2.1–2.9); penalties (3); renormalization (5); breakdown writer.
- **Tests:** L0 arithmetic golden for fixture slices (exact totals); bounds; renorm sum; penalty caps; disabled-term behavior.
- **Acceptance criteria:** fixture candidates score to 4-decimal-pinned expected totals; two runs identical; `explain --json` == embedded breakdown.
- **Definition of done:** scoring tested without launching ffmpeg; every term has ≥1 unit test.
- **Risks:** weight tuning is guesswork → fixture labels exist from day one, tuning is data-driven later.

## Sprint 6 — Ranking + diversity

- **Objective:** top-N that is diverse and attributable.
- **Deliverables:** `rank/` module implementing §7 greedy marginal-gain; `ranking.json` with selection rationale.
- **Dependencies:** S5 (breakdowns), S0 config.
- **Tasks:** overlap/sim/gap penalties; greedy loop; hard spacing; `gain_note` per decision.
- **Tests:** overlap → rejected; keyword-identical second clip loses to spaced one; margin stop; tie-break stability; determinism run.
- **Acceptance criteria:** given 6 candidates where 3 overlap the same minute, output never picks 3 from that minute when a spaced alternative exists.
- **Definition of done:** ranking pure-tested; `explain` shows why the top-6 clip was dropped.
- **Risks:** greedy ≠ global optimum → DP alternative documented but not built (interface ready).

## Sprint 7 — Captions

- **Objective:** honest, readable captions from word timestamps; correctness over style.
- **Deliverables:** `captions/` module: line builder (chars/lines/duration rules), SRT + ASS writer, word-karaoke `\k`, style config; `captions/` output; safe-area rules.
- **Dependencies:** S3 (words/sentences).
- **Tasks:** line grouping; SRT writer; ASS writer (+`\k`); readability validation (duration vs reading speed).
- **Tests:** golden SRT/ASS strings; width/duration bound checks; karaoke durations == word spans; parse-back round-trip.
- **Acceptance criteria:** every caption ≤ max_duration and ≤ max chars/line; fixtures byte-match golden files.
- **Definition of done:** captions tested without media; usable sidecars exist.
- **Risks:** carousel vs static styling taste → config-driven, default static + karaoke flag.

## Sprint 8 — Vertical reframing

- **Objective:** 9:16 output with a *simple, stable* crop path; measured input→output mapping.
- **Deliverables:** `reframe/` module: mode `center` (and interface for `faces`/`target`), crop math (AR→even dims), blur-pad path for very-wide, scale to 1080×1920.
- **Dependencies:** S1 (media AR), S0 config.
- **Tasks:** crop geometry; center mode; blur-pad; even-dim rounding + chroma alignment (offset alignment to 2); `output` config; kept deterministic-by-closed-form (no smoothing needed for center).
- **Tests:** geometry table (16:9, 4:3, 1:1, 9:16, 21:9) exact; rendered frame dims via ffprobe; blur-pad for 21:9; rounding rules.
- **Acceptance criteria:** all listed ARs map to 1080×1920 without letterboxing surprises; center mode = deterministic.
- **Definition of done:** reframe pure-tested (geometry) + L3 ffprobe check on rendered fixture.
- **Risks:** deep crop loses context on active scenes → `blurbad_threshold` + `focus`/`faces` roadmap; not solvable in MVP, documented.

## Sprint 9 — FFmpeg rendering

- **Objective:** trim/crop/scale/subs/normalize/encode from JSON only (no source re-analysis).
- **Deliverables:** `render/` module: filter graph builder, static-gain loudness from measured LUFS, burn-in via subtitles filter (libass), atomic output (temp+rename), preset/crf config; `clips/` output.
- **Dependencies:** S7 (caption files), S8 (crop plan), S5/S6 (timings from ranking.json).
- **Tasks:** filter graph construction; loudness gain application; burn path + no-burn; atomic writes; manifest stamping (ffmpeg version, model, config, filters string).
- **Tests:** L3: rendered clip passes ffprobe assertions (dims, px fmt, duration ±100 ms, audio stream); burn vs sidecar equality; `--force` re-render.
- **Acceptance criteria:** `clipper render ranking.json` produces valid clips with no dependence on source video bytes after analysis (only the video file itself as decode input).
- **Definition of done:** render e2e on fixture; one command from JSON → clips.
- **Risks:** subsecond seek discrepancy between analysis frame-time base and render decode → derive render `-ss` from the same ffprobe timebase (S1 single source of truth).

## Sprint 10 — Preview / report / explain

- **Objective:** developer can see *why* without reading source.
- **Deliverables:** `report/` module: per-candidate thumbnails, contact sheets (ImageMagick if present), timeline strip, `report.html`, `explain` JSON+YAML renderers.
- **Dependencies:** S5/S6 (data), S1 (frame extraction for thumbnails).
- **Tasks:** thumbnail extraction (frame at candidate mid), montage, HTML generator (inline CSS, no JS framework), explain renderer.
- **Tests:** HTML contains score table row per candidate; thumbs exist + correct dims; explain output identical to embedded breakdown.
- **Acceptance criteria:** `clipper report` and `clipper preview` work against existing JSON with zero analysis rerun; report renders offline.
- **Definition of done:** debugging loop (analyze→inspect→tune→render) fully offline and usable.
- **Risks:** HTML bloat → single self-contained file, CSS inlined, images embedded base64 or as links (config/`webfont-free` default).

## Sprint 11 — Integration hardening

- **Objective:** the full loop is trustworthy and packaged.
- **Deliverables:** one-shot `clipper run`; determinism test suite (L4); degraded-mode matrix; README quickstart; AUR-ready packaging metadata; CHANGELOG; docs proofread (all docs link-checked).
- **Dependencies:** S0–S10.
- **Tasks:** wire `run` = analyze→…→report; L4 determinism; degraded matrix tests; README; CHANGELOG; doc cross-link check.
- **Tests:** full L4; e2e `clipper run --top 3` on the 6-min fixture asserting success criteria (PRD §8); degraded matrix.
- **Acceptance criteria:** PRD §8 list checked 1–7; determinism suite green on archlinux CI.
- **Definition of done:** `clipper v.mp4 --top 3` is the one-command proof; docs accurate.
- **Risks:** last-mile integration bugs (flag vs config precedence) → dedicated e2e cases.

## Sprint 12 — Gamer two-zone reframe

- **Objective:** `--profile gaming` produces two-zone 1080×1920 clips; default run unchanged.
- **Deliverables:** `ReframePlan` v2 (`layout` strategy + `zones`), `reframe.geometry` gamer plan builder,
  `render/graph` vstack composite + burn position, `gaming` profile reframe keys, CONFIGURATION/CLI_SPEC/ARCHITECTURE updates.
- **Dependencies:** S8 (geometry/even rules), S9 (render graph).
- **Tests:** L0 zone geometry goldens (16:9, 4:3, 9:16 inputs; even dims, full cover, no overlap;
  byte-stable twice); L0 config validation (fraction ∈ (0,1), region ⊂ [0,1]², canvas tiling);
  L3 ffmpeg composite → 1080×1920 + vstack acceptance on ffmpeg 9.0.1; regression default run still
  center; L4 full run with gaming profile byte-identical (corpus + clips).
- **Acceptance criteria:** `clipper run X --profile gaming` → 3 two-zone clips; `clipper run X` → center
  (regression); determinism green incl. gamer profile.
- **Definition of done:** above green; docs in same change; SPRINT_STATUS flip.
- **Risks:** vstack on ffmpeg 9.0.1 (probe L3 early); even-rounding per zone must sum exactly (assert);
  existing `gaming`-profile users now get gamer output — intended, documented as drift (CONFIGURATION §2).

## Sprint 13 — Captions-actual (offline-verifiable) — **done**

- **Objective:** captions render in clips; provable offline and in CI; real whisper available on this machine.
- **Deliverables:** `transcript.path` ingest (+ validation + manifest stamp), fixture golden SRT/ASS,
  captions-on L4, burn-smoke test (env-gated on libass), DEPENDENCIES AUR whisper install doc, sample
  run with burn.
- **Dependencies:** S7 (captions), S12 (burn position on composite).
- **Tests:** L1 transcript-path ingest (valid / schema-broken / missing-words → hard error, not silent);
  golden SRT/ASS byte-match with aligned fixture; L4 captions-on determinism (no whisper needed);
  burn-smoke (`libass` gate); ADR-018 readability bounds.
- **Acceptance criteria:** captions-on L4 green in default suite; sample run local →
  `render.json.burn=True` + visually confirmed captions (whisper installed) OR documented offline
  demo on aligned fixture.
- **Definition of done:** above green; docs; ADR-021 for `transcript.path`; SPRINT_STATUS flip.
- **Risks:** no network → whisper never installable here (offline demo path still proves correctness);
  fontconfig must ship a usable font for libass burn (Arch default ok; DEPENDENCIES §1).

**Landed (Sprint 13):** `transcript.path` loads + validates a saved `transcript-info` document
(`scoria/transcript/file.py` + `analyze_transcript` branch; broken doc → `TranscriptError`, exit 1, never
silent); `manifest.json.transcript_source ∈ {file, whisper.cpp, null}`; `verify-env` gains a
`transcript_file` row; fixture `tests/fixtures/transcript_info.json` = the whisper golden as a static doc
(18 words / 4 sentences, `segment_end_indices` preserved, ADR-013 hints). Default-suite tests: file-ingest
equality with the whisper path (under the 4-decimal contract), hard-error matrix, manifest stamps,
captions-on L4 with two-run byte-identity incl. SRT/ASS sidecars, burn-smoke gated on libass. Sample run on
the 4 s planted fixture → `render.json.burn=True`, burned-frame ≠ bare-frame pixel evidence in the caption
band; `verify-env` reports the offline `transcript_file` tool. This is the **last planned sprint**;
README/CLI_SPEC/DEPENDENCIES/ROADMAP/CONFIGURATION/ARCHITECTURE document the offline caption route.

## Sequencing notes (deviations from initial draft)

- **S4 drags a minimal scene-detection from S8/Svisual** — candidates need scene boundaries *before* scoring,
  and rendering doesn't. Visual scene list → segment inputs (S4); full visual feature layer (motion → scoring)
  is folded into S4's sibling in the projects sprint where the `visual_activity` term lands. This ordering
  change keeps "boundaries before scoring" honest.
- **Captions (S7) before reframe (S8)** — captions only need transcript + config; reframing needs render. It
  also de-risks the caption engine (the oldest risk) earlier.
- **Determinism tests distributed** — S2, S3, S5, S6 each carry a determinism run; the full L4 suite waits
  for S11 to cover cross-stage invariance.

## Definition of done (global)

Sprint is Done when: all its acceptance criteria pass on fixtures, CI green, artifacts openable by the next
sprint's contracts unchanged, no new `# noqa`/disabled tests, docs in this directory check out (cross-links
resolved), and DECISIONS.md is updated for anything the sprint overturned.