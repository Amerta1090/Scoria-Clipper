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

## ADR-011 — PyYAML as the config-file parser
- **Context:** CONFIGURATION.md defines config as YAML. Options: PyYAML (de-facto standard, pure-Python wheel, BSD), ruamel.yaml (round-trip preservation, heavier), or a hand-rolled subset parser. We only read YAML — we never need to rewrite user config files.
- **Decision:** `yaml.safe_load` via PyYAML only (`load_yaml` in `config/load.py`); a non-mapping or unparseable file raises `ConfigError` (exit 2). `safe_load` avoids arbitrary object construction.
- **Consequences:** One more runtime dep (small, pure-Python); writer side never needs YAML round-trip, so `dump_yaml` is a one-way `safe_dump` for `config show`/`write-defaults`.
- Status: **Accepted**.

## ADR-012 — Runtime deps minimal + PEP 735 `dependency-groups` for dev tooling
- **Context:** ADR-001 gates dev deps behind a dev "extra". `uv` treats `[project.optional-dependencies].dev` as an optional extra (installed only with `--extra dev`), which silently breaks `uv sync && pytest`. Runtime deps must stay minimal: numpy, pydantic, PyYAML, typer, rich.
- **Decision:** Dev tooling (ruff, pytest, pytest-cov) moves to a PEP 735 `[dependency-groups] dev = [...]`, which `uv sync` installs by default and `uv sync --no-dev` (production/CI runtime) skips. Runtime deps are enumerated in DEPENDENCIES.md §1/§4.
- **Consequences:** Fresh clones get a working test env from plain `uv sync`; the runtime surface is still exactly the five declared packages; `--locked` CI is deterministic.
- Status: **Accepted**.

## ADR-013 — Whisper.cpp ≥ 1.9 JSON format drift: word timestamps come from `t_dtw` tokens
- **Context:** The docs (and ADR-004) assumed whisper's `-oj` produced `result.segments[].words[]{t0,t1}`. A built whisper.cpp 1.9.4-dev emits `result.language` + a **top-level `transcription[]`** with per-token `tokens[]{text, id, p, t_dtw}`; there is **no `words` array, no `t0/t1`** anywhere in the JSON. Timestamps exist only when flash-attn is disabled (`-nfa`; it defaults ON and silently kills DTW) **and** `--dtw <preset>` is passed — the preset is a model-size token (`tiny.base.small.medium` variants; `large` has no preset). Segment-level `timestamps`/`offsets` are garbage in this build; `t_dtw` is the token start tick in **centiseconds**; special tokens (`[_EOT_]`) carry `t_dtw = -1`.
- **Decision:** The bridge pins an exact arg surface (`-bs 0 -nt -np -sow -nfa -dtw <preset> -ojf`), reconstructs words from contiguous BPE tokens (a leading space starts a word), reads `word.start` = first token tick and `word.end` = last token tick (the format has no token end — `end` is an approximation the monotonic snap + sentence grouping absorb), and ignores segment offsets entirely.
- **Consequences:** No dependency on whisper-internal word segmentation; word `end` slightly overstates each word's true end (gap math uses the next word's `start`, so pauses stay conservative). Unknown/absent `--dtw` preset → `TranscriptError` (exit 1). A future whisper build restoring `words[]` would be read through the same tokens path — unchanged contract.
- Status: **Accepted (Sprint 3, validated live against `ggml-small.bin` + 1.9.4-dev)**.

## ADR-014 — Spoken-fixture strategy: static JSON golden is primary, `espeak-ng` real-bridge smoke is env-gated (resolves OQ3)
- **Context:** OQ3 asked whether transcript fixtures are static JSON or need audio generation. STT output is deterministic-only *for a fixed binary+model*, so generated-audio goldens would still need whisper installed (+model) in CI — a heavy, network-gated dependency.
- **Decision:** The transcript golden is a **frozen static JSON file** (`tests/fixtures/transcript_small.json`, whisper 1.9.4 `-ojf` shape) that tests parse → normalize → group without any STT tool. A **real-bridge smoke test** (decode → whisper-cli → parse, asserting non-empty `words` and correct sidecar naming) is gated behind explicit env (`SCORIA_WHISPER_BIN` + `SCORIA_WHISPER_MODEL`) and skipped otherwise. `espeak-ng` remains an **optional** test-only dependency for fixtures that need real speech (as TESTING.md §2 allows).
- **Consequences:** CI stays offline and whisper-free (all goldens pass without STT); the real bridge is still exercised on dev machines via the env-gated smoke. No audio fixture generation is required in tests.
- Status: **Accepted (Sprint 3).**

## ADR-015 — Sprint 4 scope: `visual/` = ffmpeg `scdet` scene changes only; motion intensity deferred (resolves Open Question 2)
- **Context:** OQ2 asked whether S4's "minimal scene detection" should be a formal `visual/` module. S4 needs scene cuts as candidate boundaries now; `visual_activity` (motion) and faces are scoring/reframing signals that are not required for boundaries.
- **Decision:** A new `scoria/visual/` module ships **scene changes only**, read from ffmpeg's scdet filter INFO lines (`lavfi.scd.score`/`lavfi.scd.time`), computed in one pass at `fps=4,scale=64:36,format=gray` with `trim` preserving absolute timestamps. Threshold mapping: config `[0,1]` → scdet percentage ×100. Motion intensity / `visual_activity`/`face_presence` are deferred, but the `visual/` pass already emits `visual-info` (a stable contract) and the interface plus the `visual_activity` weight reserve their place.
- **Consequences:** Scene-change boundaries work end-to-end in S4 (fixture = black→white hard cut); `visual_activity` scoring stays a no-op term until the motion pass lands; no OpenCV (per ADR-003). Visual is degradable (`--no-visual` → `visual: null`, `["visual"]` degraded) like the other stages.
- Status: **Accepted (Sprint 4).**

## ADR-016 — Boundary & candidate semantics for segmentation (dedupe, source order, window rules)
- **Context:** Candidate starts/ends come from four heterogeneous sources (sentence/noun boundaries, silence intervals, scene changes) whose raw edits overlap by ms and order differently.
- **Decision:** (1) All boundaries are unioned and **deduped within 50 ms** keeping the canonical source order `sentence_start, sentence_end, silence_start, silence_end, scene`; only the earliest surviving source label is kept per time. (2) Windows: A = nearest boundary to the preferred-length band (`segment.preferred`, tie → earlier), B = last boundary ≤ start + max_duration with a `hard_cut_margin` grace band, else hard cut at max+margin (`hard_cut` flag); ≤ `max_candidates_per_start` per start, duplicate (start,end) windows dropped. (3) Slices: sentences/words are half-open `[start,end)`, scene events are inclusive of their end, audio is a compact `[i0,i1]` window-index range.
- **Consequences:** Deterministic, bounded O(boundaries) candidate counts; every rule is config-keyed; the raw contract is `analysis.json`-style JSON (`candidates.json`) for later scoring stages.
- Status: **Accepted (Sprint 4).**
---

## Open questions
1. Default output vertical (9:16) even for portrait 4:3 sources — decided yes (blur-pad), but keep `--no-vertical` escape.
2. Whether S4's folded-in "minimal scene detection" should formally become a `visual/` module in S2 rather than S4 — **Resolved in Sprint 4: `visual/` module exists (ADR-015), shipping scene changes only via scdet; motion deferred.**
3. ~~`espeak-ng` for spoken fixture media — optional test-only dependency; decide in Sprint 3 whether fixtures are static JSON or need audio generation.~~ **Resolved in Sprint 3: static JSON golden primary, env-gated real-bridge smoke + optional espeak-ng (ADR-014).**
4. CONFIGURATION.md §3's caption-readability rule (`captions.max_duration ≥ (chars_per_line·max_lines)/(wpm/60)`) was **not** implemented in the Sprint 0 config schema: the shipped defaults (`max_duration: 4.5`) contradict it, and it is really Sprint 7 (captions) logic. Decide at Sprint 7 whether to adopt it (then adjust defaults) or drop the rule; needs an ADR either way.