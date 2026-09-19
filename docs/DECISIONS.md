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

## ADR-017 — Ranking penalty scale: λ·ratios applied in 0–100 score-units (Sprint 6 interpretation)
- **Context:** SCORING_ENGINE.md §7 leaves `ov_pen/sim_pen/gap_pen` dimensionless while candidates score 0–100 and `min_margin` defaults to 20. If penalties were λ·ratio added to a normalized 0–1 total, a fully-overlapping sibling of an equal-score clip would still retain ~99 % of its value and the sprint AC ("never 3 picks from the same minute") would fail: greedy would keep stacking the same minute.
- **Decision:** Ranking penalties are computed on the **0–100 score scale**: `ov_pen = 100·λ_ov·min(1, Σ overlap_seconds over chosen / duration)`, `sim_pen = 100·λ_sim·max over chosen Jaccard(normalized token sets from `keyword_density.window_words`)`, `gap_pen = 100·λ_gap·clamp((preferred_gap − gap_to_nearest_chosen)/preferred_gap, 0, 1)` with `preferred_gap = preferred_gap_factor·duration`. A fully overlapping clip loses its whole score (σ → ~0 under margin ≥ 0), margins/tie-breaks compare directly to totals, and `min_margin` (default 20) is a real 20-point cut. Ties resolve by (earliest start, stable id). `hard_min_start_gap` is a hard exclusion (recorded, not scored). Greedy is O(n·k) with the DP alternative reserved behind the same interface (ADR-006).
- **Consequences:** `rank_candidates` is pure (candidates.json + config → ranking.json), every selection stores its gain decomposition + `gain_note`, and the full per-step marginal-gain log lives in `ranking.json.decisions` so `explain` can report why a top candidate was dropped. On the Sprint 5 golden fixture the default-margin top-3 stops early with `[c0006, c0014]` (margin stop) — the crowded 12–70 s minute contributes one clip.
- Status: **Accepted (Sprint 6).**

## ADR-018 — Caption readability rule adopted: `max_duration ≥ (chars_per_line·max_lines/5)/(wpm/60)` (resolves OQ4)
- **Context:** OQ4 left Sprint 0's caption-readability rule from CONFIGURATION.md §3 unimplemented — the shipped
  `captions.max_duration: 4.5` contradicted it — and required an ADR either way at Sprint 7. The literal rule
  `max_duration ≥ (chars_per_line·max_lines)/(wpm/60)` is unusable with sensible reading speeds (42·2 = 84
  "chars" as words would need ~1120 wpm to justify 4.5 s), so adopting it also pins the missing units.
- **Decision:** (1) Adopt the rule with **5 chars ≈ 1 word** (average English word length) and a new
  `captions.wpm` key (default **200**, the common prose reading speed). (2) The default `max_duration` becomes
  **5.1** (the computed minimum 5.04 rounded up to 1 decimal): `(42·2/5)/(200/60) = 5.04 s`. (3) Validation is a
  config-load error (exit 2) with the computed minimum in the message. (4) Line building is deterministic with
  two documented correctness-over-style exceptions: a single word longer than `chars_per_line` occupies its own
  line, and a single word longer than `max_duration` stays whole (words are never split or dropped).
- **Consequences:** `CaptionsConfig` gains `wpm`; `max_duration` default 4.5 → 5.1; `tests/fixtures/config_good.yaml`
  updated (40×2 chars @200 wpm ⇒ min 4.8, fixture now 5.0). `captions/lines.py` clamps window boundary words,
  chunks by `max_duration` (span = last word end − first word start), wraps to ≤ `max_lines` lines ≤
  `chars_per_line` chars, prefers sentence-end reflow when `prefer_sentence_breaks`, and drops blocks below
  `min_word_count`. `captions.json` (`schema: captions`, CAPTIONS_VERSION 1) carries word timestamps per block so
  ASS `\k` karaoke equals word spans and render (S9) can burn without re-reading analysis.
- Status: **Accepted (Sprint 7).**

## ADR-019 — Id-keyed artifact naming for clips/captions/previews (retroactive)
- **Context:** Sprint 7 sketched `clip-01.srt/.ass` names in ARCHITECTURE.md §6, but clip `id` (`c0001`-shaped) is the rank-independent identity: rank changes with `--top`/config, ids do not. Sprint 7 shipped id-keyed caption sidecars (`captions/c0006.srt`) and Sprint 9 rendered `clips/<clip_id>.mp4` (`render/core.py` cites "ADR-019") — but the decision was never recorded in this log.
- **Decision:** Every per-clip artifact is keyed by the stable candidate `id`, not rank or position: `clips/<id>.mp4`, `captions/<id>.srt|.ass`, `previews/<id>.png|.sheet.png`. Rank/order mapping lives inside the JSON documents (`ranking.json.selected[].rank`, `captions.json`), never in filenames; rank-dependent naming is reserved for human-facing presentation only.
- **Consequences:** Artifacts survive re-ranking and are directly addressable by id across stages (`clipper explain proj <id>`); scripts join on id without parsing filenames. ARCHITECTURE.md §6/§11 were updated in Sprints 7/9; this entry records the decision retroactively so later sprints have a citable source.
- Status: **Accepted (Sprint 7 / Sprint 9; recorded Sprint 10).**

## ADR-020 — Report assets: ffmpeg montage + SVG timeline + PNG stills (no ImageMagick); `report.embed_images`
- **Context:** SPRINT_PLANNING.md §S10 sketched "contact sheets (ImageMagick if present)" and "images embedded base64 or as links (config/webfont-free default)". ImageMagick is not in the evaluated stack (DEPENDENCIES.md), and an "if present" branch would make report output depend on the host — breaking the determinism contract (ADR-010).
- **Decision:** (1) Contact sheets are one-row `hstack` montages built by the already-required ffmpeg (`report/graph.py:contact_sheet_args`), not ImageMagick — no new runtime dependency, no host-dependent branch. (2) Stills are lossless PNG grabbed through the pinned ffmpeg surface with `-ss` input seek (same frame-time surface as render). (3) The timeline strip is deterministic SVG (pure string builder, no ffmpeg), embedded inline in `report.html` and written as `previews/timeline.svg`. (4) `report.html` carries no timestamps, so it is byte-stable. (5) New `report.embed_images` (default `true`) selects base64 data URIs (single self-contained file) vs relative `previews/` links; `report.preview_width` / `per_candidate_strips` / `include_score_table` were already schema keys.
- **Consequences:** `report`/`preview` are reproducible on any machine with ffmpeg (no optional tool); L0 tests pin the arg surface without ImageMagick, and L3 ffprobe checks assert exact still dims (`preview_width` × even height; sheet = N × preview width). `previews.json` (`schema: previews`, PREVIEWS_VERSION 1, `preview_version: still.mid.v1`) joins `ranking.json` by clip id (ADR-019).
- Status: **Accepted (Sprint 10).**

## ADR-021 — `transcript.path`: load a saved transcript-info document instead of running whisper.cpp
- **Context:** Sprint 13 needs captions to *actually render* in clips, but whisper.cpp is not installed on
  the authoring machine and cannot be installed offline/CI — `transcript.enabled: false` degraded every run
  (`degraded=['transcript','captions_unavailable']`), so the whole captions-on chain (scoring transcript
  terms, SRT/ASS, burn) was untestable without STT.
- **Decision:** (1) New `transcript.path: ""` config key — when set (with `transcript.enabled: true`) the
  transcript stage **loads + contract-validates** a saved `transcript-info` document (schema match,
  non-empty `words`, strictly monotonic timestamps) instead of running whisper.cpp. (2) Broken docs are a
  hard error (exit 1), never silent. (3) `manifest.json` stamps `transcript_source: file|whisper.cpp` so a
  run's transcript provenance is inspectable. (4) Whisper.cpp stays the default runtime engine; this is an
  addition, not an overturn of ADR-004/ADR-014. (5) Given identical words, file-ingest and whisper produce
  the identical `analysis.json.transcript` (same normalization + sentence grouping), extending
  byte-reproducibility to the captions chain without an STT binary.
- **Consequences:** offline/CI runs prove captions correctness against an aligned golden fixture; the sample
  workflow gets a documented offline demo path if the AUR whisper install is unavailable (no network).
- Status: **Accepted (Sprint 13).**

---

## ADR-022 — Gamer two-zone reframe: plan v2 + split/vstack composite (Sprint 12)
- **Context:** The `gaming` profile existed since Sprint 8 but produced the same center-crop clips as every
  other profile — its intended output was a let's-play vertical layout (gameplay + facecam PiP), which
  requires geometry beyond the single-window center plan (`ReframePlan` v1: one crop/content/pad window).
  Focus modes (`faces`/`target`) were already post-MVP, so the v2 plan had to stay closed-form and
  deterministic with no new segments, RNG, or per-clip variation (a plan is still video-wide).
- **Decision:** (1) `ReframePlan` v2 (`REFRAME_VERSION 2`, `plan.v2`) gains `layout: center|gamer` and
  `zones: [GamerZone]`; v1 files still load (layout defaults to `center`, zones null). (2) `mode: gamer`
  (selected by the `gaming` profile via `reframe.mode`) builds two zones that tile the 1080×1920 canvas
  exactly: gameplay on top (`round_even(out_h × v_fraction)`, center-anchored cover-fit crop → scale) +
  facecam PiP on the bottom (the remainder, from the configured normalized source region, cover-fitted
  inside it). v1 lenses: `anchor: center` only; region/canvas config in `reframe.gamer`. (3) Render
  composites with `split=2` + per-zone `crop,scale,setsar=1` + `vstack=inputs=2`, burning captions after
  the composite. `setsar=1` is required: on this ffmpeg (9.0.1), naive `scale` preserves SAR and yields
  fractional pixels (676:675 → DAR 169:300 ≈ 9:16, not literal 9:16), violating the exact-tiling
  contract. (4) Existing `gaming`-profile users now get gamer output — intended, documented drift
  (CONFIGURATION.md §2); default `clipper run X` stays center, regression-tested.
- **Consequences:** the gamer path ship average-real-calibre verticals deterministically (L3 ffprobe +
  L4 two-run byte-identical suite in the default pytest run); post-MVP focus modes extend `zones` (e.g.
  per-zone anchor/region variants) without changing the v2 contract; `render.json` clip `filters` records
  the exact composite per clip for provenance.
- Status: **Accepted (Sprint 12).**

---

## Open questions
1. Default output vertical (9:16) even for portrait 4:3 sources — decided yes (blur-pad), but keep `--no-vertical` escape.
2. Whether S4's folded-in "minimal scene detection" should formally become a `visual/` module in S2 rather than S4 — **Resolved in Sprint 4: `visual/` module exists (ADR-015), shipping scene changes only via scdet; motion deferred.**
3. ~~`espeak-ng` for spoken fixture media — optional test-only dependency; decide in Sprint 3 whether fixtures are static JSON or need audio generation.~~ **Resolved in Sprint 3: static JSON golden primary, env-gated real-bridge smoke + optional espeak-ng (ADR-014).**
4. ~~CONFIGURATION.md §3's caption-readability rule (`captions.max_duration ≥ (chars_per_line·max_lines)/(wpm/60)`) was **not** implemented in the Sprint 0 config schema: the shipped defaults (`max_duration: 4.5`) contradict it, and it is really Sprint 7 (captions) logic. Decide at Sprint 7 whether to adopt it (then adjust defaults) or drop the rule; needs an ADR either way.~~ **Resolved in Sprint 7: rule adopted with 5 chars/word + `captions.wpm` (200) and `max_duration` default 5.1 (ADR-018).**