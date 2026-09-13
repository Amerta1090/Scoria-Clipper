# Architecture

Covers layering, module map, the full pipeline (merged from the draft "PIPELINE.md" — see note at end),
data contracts, artifact layout, and the determinism model.

## 1. Layering rule (non-negotiable)

Four concern layers, strictly separated. A layer may consume the output of lower layers, never mix them.

```
[Analysis]  produce raw data + feature metrics   → analysis.json
[Scoring]   features → normalized sub-scores     → candidates.json (enriched, explainable)
[Ranking]   scores → diverse top-N               → ranking.json
[Rendering] candidates → final media             → clips/ captions/ report.html
```

- `Score` modules never call ffmpeg. `Analysis` never knows about weights. `Render` never re-scores.
- Every cross-layer boundary is a **typed, JSON-serializable data contract** (pydantic models), so layers
  can be run in separate invocations.
- `clipper video.mp4` is only an orchestrator that calls the four stages in order; it adds no logic.

## 2. Technology

- **Language:** Python ≥3.12 (host has 3.14). Rationale: fastest path for numpy features + text processing +
  clean CLI; the heavy lifting (decode, encode, STT) is delegated to native tools, so Python performance is
  irrelevant to the hot path. See DEPENDENCIES.md for the Rust trade-off.
- **Package:** `scoria` (directory name; unique-ish, short). **Binary/entry point:** `clipper`.
  ("dvc" rejected — collides with Data Version Control. See DECISIONS.)
- **Media backends:** ffmpeg/ffprobe (decode, analysis filters, encode, burn-in via built-in libass), whisper.cpp (STT), numpy (window math), ImageMagick (contact sheets).
- **CLI:** typer (click-adjacent, typed). **Config/data validation:** pydantic v2. **Tests:** pytest. **Lint:** ruff. **Dep manager:** uv. Dev-only.

## 3. Module map

```
scoria/
├─ cli/            typer app, arg parsing, one-shot orchestrator
├─ config/         pydantic config schema, profile deltas, validation, CLI->config merge
├─ ingest/         ffprobe metadata, container validation, stream detection
├─ audio/          PCM extraction (ffmpeg f32le), numpy window features, silence, loudness
├─ transcript/     whisper.cpp bridge, word timings, sentence grouping, punctuation inference
├─ visual/         grayscale low-res frame pass, scene change (scdet-derived), motion intensity
├─ segment/        boundary builder (silence ∪ sentence ∪ scene), candidate window generator
├─ score/          feature vec builder, sub-score functions, weights, penalties, ScoreBreakdown
├─ rank/           diversity-aware greedy selection (temporal + keyword-Jaccard penalties)
├─ captions/       line-building (chars/min duration), SRT + ASS(karaoke), styling
├─ reframe/        crop plan: focus point, EMA smoothing, clamp/bounds, even-dim
├─ render/         ffmpeg filter graph builder: trim/crop/scale/subs/loudness/encode
├─ report/         preview assets, contact sheet, report.html, `explain` text renderer
├─ project/        project-dir IO (read/write JSON with stable serialization contract)
└─ util/           logging, stable float/JSON formatters, deterministic ffmpeg runner
```

Design rules:
- Sub-score functions live in `score/` modules as **pure functions** `f(feature_vector_slice) -> float`, one per signal. Zero I/O. This is what makes unit testing + determinism trivial.
- The ffmpeg runner in `util/` centralizes every subprocess invocation (fixed arg order, env pinning, failure reporting). `-nostdin` is pinned on `run_ffmpeg`; `run_ffprobe` omits it because this ffprobe build (n9.0.1) rejects the flag and ffprobe only reads stdin when given `-` as input (ingest always probes a spooled file). No module shells out on its own.
- All file writing goes through `project/` so the serialization contract (sorted keys, float precision) is enforced in one place.

## 4. Pipeline (data flow)

This section is the pipeline specification; kept in this doc because it is the spine both PRD and sprint
planning reference.

```
 video.mp4
   │  ingest: ffprobe → media.json + validity checks
   ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  ANALYSIS STAGE                                              │
 │  audio:     ffmpeg → f32le mono 16k PCM → numpy window RMS/   │
 │             energy/silence + ebur128 integrated loudness       │
 │  visual:    ffmpeg → 4fps gray 64×36 frames → scene scores +   │
 │             motion intensity per frame (numpy diff)            │
 │  transcript: whisper.cpp --output-json → words (t0,t1) →       │
 │             sentences (rule-based grouping + punct inference)  │
 │  ────────── all above merged into analysis.json ────────────── │
 │  segment:   boundaries = silence ∪ sentence ∪ scene            │
 │  candidate: window generator over boundaries (min/pref/max)    │
 │  ────────── candidates.json (raw windows, no scores) ───────── │
 └────────────────────────────────────────────────────────────────┘
   │  score:  per-candidate feature slice → sub-scores → weighted  │
   │          total − penalties → ScoreBreakdown (explainable)     │
   ▼
 candidates.json (enriched)   +  SCORING_VERSION + per-function ids
   │  rank:  greedy diverse top-N (overlap + Jaccard + spacing)    │
   ▼
 ranking.json
   │  captions: words → lines → captions/out.srt + out.ass         │
   │  reframe:  focus plan (center for MVP) → crop+scale chain     │
   │  render:   ffmpeg trim/crop/scale/subs/static-gain/encode     │
   ▼
 clips/clip-01.mp4 …   captions/*   previews/*   report.html
```

## 5. Analysis stage details

### 5.1 Audio
- Extract: `ffmpeg -i in -vn -ac 1 -ar 16000 -f f32le -` → one big float32 array with known timestamp origin.
  (1.6 s of buffer per 25 600 samples — window is 50 ms.)
- 50 ms windows → RMS, per-window energy. Silence = contiguous windows below a config threshold,
  with min-duration merge. Loudness: ffmpeg `ebur128` filter for integrated/momentary LUFS (used only for
  the render normalization gain, and as an info field).
- Deterministic: fixed window, fixed threshold, numpy reduction over the exact same float array. No RNG.

### 5.2 Visual
- Single low-cost pass: `ffmpeg -i in -an -vf "fps=4,scale=64:36,format=gray" -f rawvideo -pix_fmt gray -` →
  2304 bytes/frame → numpy.
- **Motion intensity** at frame `i` = mean abs difference (frame i − frame i−1), then smoothed.
- **Scene change** = thresholded motion spike at analysis FPS, cross-checked against ffmpeg `scdet`
  scores (we read the scores, don't re-encode). Scene boundaries recorded at media timestamps.
- This is deliberately decimated + grayscale: deterministic, cheap, and independent of source codec
  internals at 4 fps sampling.

### 5.3 Transcript
- Bridge to `whisper-cli` (whisper.cpp) with deterministic settings: fixed model file (sha256-pinned),
  greedy decoding (beam 0 / temperature 0), fixed thread count. Produces JSON with word-level `t0,t1`.
- **Sentence grouping (our rule, not whisper's):** merge words into sentences using (a) whisper segment
  ends, (b) inferred punctuation (period/question/exclamation from config + end-of-segment heuristics),
  (c) pause gaps ≥ config threshold. Output: ordered `Sentence {words[], start, end, text}`.
- Degradation: if STT is disabled/unavailable → `transcript: null`, scoring renormalizes weights
  (speech-dependent terms removed), candidate generation relies on silence + scene boundaries only.

### 5.4 Boundaries & candidates (segment/)
- Boundary sources, unioned and deduped within 50 ms:
  1. sentence starts/ends (transcript)
  2. silence intervals (audio) — used both as cut points and as "dead air" for penalties
  3. scene changes (visual)
- Candidate generation:
  - min = min_duration (default 20 s), pref = preferred window (default 35–45 s), max = max_duration (60 s).
  - For each start boundary, extend forward through sentence groups until the next sentence start would
    exceed `max`; produce at most 2 candidates per start: (A) complete sentence cut at `pref` (nearest), 
    (B) maximum extension before `max` at a boundary. If a single sentence exceeds `max`, hard-cut at `max`
    and mark `mid_sentence_end` for a completeness penalty.
  - Candidate count is bounded O(boundaries) — no combinatorial blowup; deterministic order by (start,end).
- All candidates begin life with an `aligned_to` list stating which boundaries it touches — this is what
  scoring consumes for completeness.

## 6. Artifacts / project directory

Default project dir: `<video>.scoria/` (config `project_dir`). Human-inspectable, re-runnable.

```
<video>.scoria/
├─ analysis.json        media + audio + visual + transcript + features  [STAGE 0]
├─ candidates.json      raw windows → per-candidate feature slices + ScoreBreakdown [STAGE 1+2]
├─ ranking.json         top-N with selection rationale
├─ clips/               clip-01.mp4 … (1080×1920, captions burned)
├─ captions/            clip-01.srt, clip-01.ass (word-karaoke)
├─ previews/            per-candidate thumbnails, contact-sheet-*.jpg, score strip
├─ report.html          self-contained (inline CSS), score table + explain views
└─ manifest.json        tool versions (ffmpeg, whisper model sha, scoria), config snapshot, SCORING_VERSION
```

- `candidates.json` is the **single source of truth for every scoring decision**: it carries input
  measurements, normalized values, weighted contributions, and which function id produced each number.
- JSON stability: keys sorted, floats rounded to 4 decimals, `sort_keys=True`, no trailing whitespace,
  fixed model of serialization enforced by `project/`.

## 7. Determinism model

Definition: **same input media + same config + same tool versions (whisper model file, ffmpeg build) →
byte-identical analysis.json + candidates.json + ranking.json + identical rendered clip streams.**

What we control:
- No RNG anywhere in Python. Tensor/numpy pipelines reduce in fixed order.
- Whisper: fixed model file (sha256 recorded in `manifest.json`), greedy decoding, fixed threads.
  **Honest caveat:** whisper.cpp is deterministic for fixed binary+model+settings, but *across* builds/CPUs
  SIMD/rounding can differ; determinism is guaranteed for a fixed local install, and `manifest.json` makes
  any drift detectable, not silently accepted.
- ffmpeg: fixed filter chain, fixed thread count, `-nostdin`, and — for analysis — we consume only
  decimated/lossless intermediate data (PCM f32, raw gray frames), so analysis is robust to encoder variance.
- Rendering: x264 is deterministic for a fixed build + fixed threads + fixed input. Pin thread count.
- Tie-breaking everywhere: resolve by earliest start time, then stable id.

Equivalence classes: an output is equivalent if byte-identical; no tolerance. If determinism ever proves
unreachable for some component, that component is documented and flagged in `manifest.json` (`deterministic:
false`) instead of pretending.

## 8. Scoring & ranking placement

- Score: pure functions + weights + penalties → `ScoreBreakdown`, exported in candidates.json.
  Formula, sub-score definitions and weights live in SCORING_ENGINE.md (the single source of truth for score math).
- Ranking: diversity-aware greedy over breakdowns. See SCORING_ENGINE.md §Ranking.

## 9. Rendering stage details

- Input: `ranking.json` + `analysis.json` (+ transcript for captions).
- Reframe:
  - MVP = center crop: crop width = round(source_h × 9/16) (to even), then scale → 1080×1920.
  - If source is already 9:16 → scale only. If source is portrait but narrower (<9:16) → blur-pad mode.
  - Post-MVP focus modes (`faces`) live behind the same `reframe/` interface; MVP keeps the interface.
- Captions: built in `captions/` (SRT + ASS). Burn-in aborts gracefully if libass unavailable → sidecar only.
- Audio: **static-gain normalization** from measured integrated loudness (`ebur128` pass), applied as a
  linear gain — fully deterministic — rather than dynamic `loudnorm` (dynamic mode is version/soft-dependent
  and hard to reproduce; optional flag, default off, documented in CONFIGURATION.md).
- Encode: libx264, `-crf 19 preset medium`, `-pix_fmt yuv420p`, `-movflags +faststart`. All filter graph
  parameters derived from data in ranking.json/analysis.json — never re-derived from the source at render time
  (that is what guarantees render-without-reanalyze).

## 10. Report / explain

`report.html` renders the same data `explain` prints, but as a sortable table + timeline strip + per-candidate
detail. All of it is generated from candidates.json/ranking.json; analysis never runs at report time.

## Note on the draft PIPELINE.md

The "pipeline" concern is fully covered by §4–§9 above; a separate PIPELINE.md would duplicate it. It is
merged here. If pipeline changes diverge from architecture later, re-split then.