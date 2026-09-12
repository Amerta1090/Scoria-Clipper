# Decision Log (ADR)

Chronological. Each entry: context, decision, consequences, status. New decisions get appended; overturned
decisions are superseded, never edited retroactively.

---

## ADR-001 — Language: Python (≥3.12) for the orchestration layer
- **Context:** Two native tools (ffmpeg, whisper.cpp) already do 99 % of the heavy compute. The remaining work is glue, signal math, and text processing. Rust/C++ would buy wall-time on microseconds-level numpy math and a static binary — neither needed for a local CLI, both cost iteration speed on the *riskiest* logic (sentence grouping, boundaries, scoring formulas).
- **Decision:** Python with `uv`; `score/` functions kept pure so a future re-implementation in Rust is mechanical.
- **Consequences:** Faster correctness iteration; Python 3.14/pydantic support must be verified in Sprint 0. Dev deps are gated; runtime deps stay minimal (numpy).
- Status: **Accepted** (see DEPENDENCIES.md §5).

## ADR-002 — Binary named `clipper`, package named `scoria`
- **Context:** "Deterministic Video Clipper". `dvc` collides with Data Version Control and generic "divx/dvc" meanings. Working dir is already `scoria`.
- **Decision:** Python package `scoria`, console entry point `clipper`.
- **Consequences:** Unique-enough names; `clipper` is a natural verb for users; rename is cheap pre-release.
- Status: **Accepted** (renamable pre-1.0).

## ADR-003 — ffmpeg + numpy as the signal-extraction stack (no OpenCV/librosa/MediaPipe in MVP)
- **Context:** Visual needs for MVP = scene changes + motion intensity, both derivable deterministically from a low-res gray frame pass (64×36 @ 4 fps) + numpy diff; audio needs = RMS/energy/silence/loudness, derivable from an f32le PCM pass + numpy windows. OpenCV/librosa add heavy deps for features we compute in tens of lines.
- **Decision:** ffmpeg (decode + analysis passes) + numpy (window math). OpenCV/MediaPipe deferred to the face-reframing milestone behind a prepared interface; librosa deferred to a possible music profile.
- **Consequences:** MVP installs = ffmpeg + whisper.cpp + Python/numpy. The `visual_activity`/`face_presence` interface is shared, so a face signal plugs in without touching scoring wiring.
- Status: **Accepted**.

## ADR-004 — whisper.cpp as the default STT engine (greedy, pins, degraded path)
- **Context:** Need word-level timestamps, local, deterministic-enough. whisper.cpp is a single binary, MIT, `--output-json` word spans, greedy mode possible. faster-whisper is pip-easier but a Python C-extension with CTranslate2 models and more runtime surface.
- **Decision:** whisper.cpp default; engine keyed (`transcript.engine`) so faster-whisper is a later option. Determination = greedy decode + pinned model sha + pinned threads; cross-build reproducibility documented as not guaranteed (manifest makes drift visible).
- **Consequences:** One extra native install; graceful audio-only fallback when absent. Determinism is *local-install* deterministic.
- Status: **Accepted**.

## ADR-005 — Static-gain loudness normalization (not dynamic `loudnorm`) as default
- **Context:** Dynamic loudnorm is version/soft-dependent and hard to reproduce byte-for-byte. We measured loudness anyway (ebur128).
- **Decision:** Renders normalize via a static linear gain derived from measured integrated LUFS; `loudnorm` two-pass is an opt-in with its determinism caveat documented.
- **Consequences:** Deterministic audio by construction; marginally less "perfect" peak shaping than dynamic normalization for loud content.
- Status: **Accepted**.

## ADR-006 — Greedy marginal-gain ranking (over DP)
- **Context:** "Top 5 ≠ 5 slices of the same minute" needs diversity beyond order-by-score. Options: global-optimal DP over an additive cost, or greedy marginal gain.
- **Decision:** Greedy: `score − λ₀·overlap − λ₀·sim − λ₀·gap`, deterministic, O(n·k), trivially attributable decisions. DP rejected for MVP; interface shared so DP is a drop-in later.
- **Consequences:** Sometimes sub-optimal vs global DP, always explainable; fine for v1.
- Status: **Accepted**.

## ADR-007 — Center crop reframing in MVP; faces/motion reframing post-MVP
- **Context:** Face-tracking reframing is mostly a **trajectory smoothing** problem (EMA/One-Euro, bounds, *smooth camera*) once you have a centroid — but face detection itself is the heaviest optional dependency and was cut in ADR-003.
- **Decision:** MVP ship `reframe: center` (closed-form, fully deterministic) + blur-pad for very-wide sources. `faces`/`target` modes behind the same interface, M1.
- **Consequences:** Deterministic and shippable now; vertical framing on off-center subjects is wrong until `faces`/`target` — documented limitation of the MVP.
- Status: **Accepted**.

## ADR-008 — Scoring is 100 % config-driven with renormalization, weights sum to 1
- **Context:** The user asked for tunable profiles and explainable math. If a signal is disabled, weights must not silently shift meaning.
- **Decision:** Sub-scores in [0,1], weights ≥0 normalized to 1 across enabled terms, SCORING_VERSION bumps on any math change, ScoreBreakdown embeds inputs/raw/normalized/weighted + function ids.
- **Consequences:** `explain` and `report.html` are free renders of candidates.json; tuning is data (`clipper config validate` guards sums).
- Status: **Accepted**.

## ADR-009 — PIPELINE.md merged into ARCHITECTURE.md
- **Context:** Initial doc list had PIPELINE.md separately; its content (data flow, stage ordering) is the architecture spine, duplicating ARCHITECTURE.md §4–§9.
- **Decision:** Single source of truth in ARCHITECTURE.md; re-split only if it grows to need its own TOC.
- **Consequences:** One fewer doc, no drift; editors must update one file, not two.
- Status: **Accepted**.

## ADR-010 — JSON artifacts are byte-stable and contract-checked in `project/`
- **Context:** Byte-identical outputs across runs is the determinism promise; float formatting and key order were the two failure points.
- **Decision:** One writer/reader pair in `project/`: sorted keys, floats fixed to 4 decimals, manifest stamped with tool versions + config snapshot + SCORING_VERSION. Round-trip tested.
- **Consequences:** Golden-file diffs are meaningful; scripts can hash artifacts.
- Status: **Accepted**.

---

## Open questions
1. Default output vertical (9:16) even for portrait 4:3 sources — decided yes (blur-pad), but keep `--no-vertical` escape.
2. Whether S4's folded-in "minimal scene detection" should formally become a `visual/` module in S2 rather than S4 — see SPRINT_PLANNING §Sequencing notes; will be revisited during Sprint 4 spikes.
3. `espeak-ng` for spoken fixture media — optional test-only dependency; decide in Sprint 3 whether fixtures are static JSON or need audio generation.