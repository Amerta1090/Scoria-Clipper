# Scoring Engine

This is the heart of the project. Everything here is deterministic, testable, and explainable. The formula
below is the *initial* release formula; the structure (normalize → weight → penalize → breakdown) is fixed,
the numbers are all config.

- Every number a sub-score produces is a `float` in `[0,1]` (normalized). Weights are `≥0`, summing to `1.0`
  for the enabled sub-scores (renormalized automatically when a signal is disabled, e.g. no transcript).
- Penalties are `−value` in `[0,1]`, capped per rule and in total.
- Final total: `100 × (Σ wᵢ·sᵢ − Σ penalties)`, floored at 0 and capped at 100.
- SCORING_VERSION (semver string) is stamped into candidates.json; any change to a sub-score function,
  weight set, or penalty rule bumps it. `explain` prints the version.

## 1. Identity of a score

Each `ScoreBreakdown` records, for every term:

```json
{
  "term": "completeness",
  "function": "complete_ends.sentence_align.v1",
  "inputs": {"gap_start_ms": 120, "gap_end_ms": 40, "is_sentence_start": true},
  "raw": 0.94,
  "normalized": 0.94,
  "weight": 0.20,
  "weighted": 0.188,
  "note": "starts on sentence boundary; ends 40ms past boundary"
}
```

This is what `clipper explain clip-03` prints. A rejected candidate's breakdown is equally visible.

In the serialized document the `weight` field is the **renormalized** weight (`config_weight / renorm_factor`,
see §5) — so `weighted = weight · normalized` sums with `subscore_sum` directly. Terms whose formula has no
pre-clamp return `raw == normalized`. Every term and penalty also carries its `inputs`, which is what makes a
late re-score a pure function of `candidates.json` + config.

## 2. Sub-scores (v1)

### 2.1 audio_energy — w 0.09
- Inputs: window RMS series in candidate, video-wide RMS p95 (`R95`).
- `E = mean(clamp(rms / R95))` over the candidate.
- Normalized: `s = smoothstep(E, 0.15, 0.75)` (`smoothstep` = 3x²−2x³ on the normalized blend of `E`
  between the two bounds). Rationale: below ~15 % of the video's own peak level the clip feels dead; above
  ~75 % it is indistinguishable from "loud", no extra credit.

### 2.2 speech_density — w 0.13
- Inputs: transcript word spans in window vs window duration.
- `D = speech_time / window_duration`.
- Normalized: `s = smoothstep(D, 0.30, 0.85)`. Rationale: features <30 % speech are "mostly not talking";
  above 85 % is full narration. No extra credit for monotone 100 %.

### 2.3 pacing — w 0.10
- Inputs: words-per-minute (`wpm`) in candidate, video-wide speaker baseline (`wpm_base` = video-wide WPM).
- `r = wpm / wpm_base`.
- `s = bell(r, 0.85, 1.35)` (trapezoid: linear up 0→1 between 0.85–1.0, 1 at 1.0–1.2, linear down to 0 at 1.5).
  The trapezoid knots are the spec; `pacing_band.hi` (1.35) and `wpm_base_window` are reserved config keys,
  present in the schema but unused in v1.
  Rationale: relative to the speaker's own baseline (self-calibrating), +/-25 % is the "comfortable" band.
- Keep it weak — pacing is temperament, not content.

### 2.4 hook — w 0.15
- Inputs per candidate: first-sentence features, energy/motion bursts in first 2 s, hook-phrase hits.
- Combined: `hookRaw = max(hook_phrase, open_question, open_short, open_burst)` where:
  - `hook_phrase` = match of a configured hook phrase in first 30 % of window (weighted by position: earlier = 1, at 30 % = 0.5; past 30 % → capped at 0.5).
  - `open_question` = first sentence ends with `?` → 1, but 0 if first sentence length > 12 words (a long question is not an opener).
  - `open_short` = first sentence ≤ 8 words → 1.
  - `open_burst` = mean energy burst / motion burst in first 2 s ≥ 3× the clip's own mean → 0.8, else scaled.
- `s = clamp(hookRaw, 0, 1)`.
- Rationale: the first ~2 s decide retention; we reward a crisp, question-like, phrase-marked or punchy open.
  All four openers are cheap and deterministic; no semantics involved.

### 2.5 completeness — w 0.20 (largest)
- Inputs: boundary alignment at start and end.
- `s = 0.5·g_start + 0.5·g_end`, where:
  - `g_start = 1` if candidate starts on a sentence start boundary; `0.5` if it starts on a scene or silence
    boundary within 300 ms of a sentence start; else `max(0, 1 − gap_ms/2000)`.
  - `g_end` same rule for the end.
- Rationale: starting a thought and finishing it is the single strongest "works standalone" signal for
  short-form. This is deliberately the heaviest weight.

### 2.6 visual_activity — w 0.10
- Inputs: scene-change density `sc` (changes/min) in candidate.
- `s = bell(sc, 0.0, soft, hard, 0.0)` with soft=1.5 changes/min, hard=6 changes/min: 0 at 0 changes (static
  talking head), trapezoid 0→1.0 as density rises to 1.5–2.5/min, then falls to 0 by 6/min.
- Rationale: a little motion is alive; a cut every 10 s is editing noise. Non-monotonic on purpose.

### 2.7 keyword_density — w 0.06
- Inputs: configured keyword list, normalized transcript text of the window.
- `hits/min` → `s = smoothstep(hits_per_min, 0.5, 3.0)`.
- Rationale: term-frequency only. Small weight; a keyword hit never rescues a broken clip. Caps apply
  (see §4) so keyword-stuffing can't dominate.

### 2.8 sentence_quality — w 0.06
- Inputs: mean words-per-sentence in candidate vs comfortable band (config, default 6–18).
- `s = bell(wps, 6, 9, 18, 22)` (trapezoid 0→1 from 6→9, 1 in 9–18, down to 0 at 22+).
- Rationale: walls of text or choppy fragments hurt watchability.

### 2.9 face_presence — w 0.00 (post-MVP, default disabled)
- When a face signal exists: `s = coverage_fraction · size_boost · centered_boost` (each in 0–1).
- Disabled ⇒ weight renormalized across enabled terms (see §5). Interface ready now, signal later.

## 3. Penalties (capped, configurable)

| Penalty | Rule | Cap |
|---|---|---|
| `leading_silence` | silence ≥ cfg edge_silence_tol (default 0.4 s) at window start | 0.10 |
| `trailing_silence` | same at window end | 0.10 |
| `dead_air` | internal silence > 1.5 s (sum), scaled | 0.15 |
| `mid_sentence_start` | start inside a sentence (gap to start boundary > 300 ms) | 0.15 |
| `mid_word_end` | end lands inside a whisper word span | 0.20 |
| `low_energy_tail` | last 1 s mean RMS < 30 % of clip mean | 0.05 |
| `flub_repeats` | adjacency-repeat ratio ≥ 0.5 % of words | 0.05 |
| `peak_clipping` | peak fraction > 2 % | 0.02 |
| Total penalty | sum capped | 0.35 |

Penalties apply *after* weights; `explain` shows both the rule and the resulting `−value`.

## 4. Default weight set (v1)

| Sub-score | weight |
|---|---|
| completeness | 0.20 |
| hook | 0.15 |
| speech_density | 0.13 |
| pacing | 0.10 |
| visual_activity | 0.10 |
| audio_energy | 0.09 |
| keyword_density | 0.06 |
| sentence_quality | 0.06 |
| face_presence | 0.00 (disabled → renormalized out) |
| **Σ** | **0.89 → renormalized to 1.00** |

Ranking intuition encoded here: *complete and hooky* dominate; *speech present and at natural pace* support;
*visual and keyword* nudge. Penalties are unbounded-in-justification but capped in effect so one flaw can't
sink a great clip to zero.

## 5. Renormalization

When a signal is disabled (e.g., `transcript: off`, or `face_presence: off`), its weight is removed and all
enabled weights are scaled by `1/Σ(enabled)`. Always documented in the breakdown (`renorm_factor` and
`scoring_meta.signals_disabled`).

No transcript removes every transcript-dependent term: `speech_density`, `pacing`, `hook`, `completeness` (its
sentence-boundary grades have nothing to grade), `keyword_density`, `sentence_quality`. No visual signal
additionally removes `visual_activity`. `face_presence` has no feature producer in MVP, so it is *always* in
the disabled set. The disabled set is stored in the enriched document so a re-score renormalizes the same
weight set without the analysis artifacts.

Sub-scoring is invariant: a range check runs at config load so the sum of enabled weights ∈ [0.99, 1.01].

## 6. Explainability

`clipper explain <project> clip-03` renders:

```
clip-03  04:12.5–04:51.2 (38.7s)   total 87.4 / 100   [score v1.3.0]
completeness   0.188  (w .20 · s .94)   starts@sent-end; ends 40ms past boundary
hook           0.135  (w .15 · s .90)   "yang perlu kamu tahu?" question opener
speech_density 0.117  (w .13 · s .90)   78% speech
pacing         0.082  (w .10 · s .82)   wpm 168 vs base 160
visual_activity 0.057 (w .10 · s .57)   1.9 changes/min
audio_energy   0.051  (w .09 · s .57)
keyword_density 0.048 (w .06 · s .80)   "cara"×1 "tutorial"×1
sentence_quality 0.045 (w .06 · s .75)
penalties      −0.080                 trailing_silence −.05, dead_air −.03
```

The same data is in `candidates.json` per candidate; `report.html` is a richer rendering.

## 7. Ranking & diversity (rank/)

Goal: TOP 5 ≠ 5 slices of the same minute.

Algorithm: **greedy with marginal gain**, deterministic and explainable.

```
order candidates by (score desc, start asc)
for k in 1..topN:
    best = argmax over remaining c of G(c)
    G(c) = score(c) − ov_pen(c, chosen) − sim_pen(c, chosen) − gap_pen(c, chosen)
    select best if G(c) ≥ min_margin (default 20), else stop
```

- `ov_pen` = λ_ov · (temporal overlap seconds / candidate duration), λ_ov default 1.0 (a fully overlapping
  clip loses its whole score).
- `sim_pen` = λ_sim · Jaccard(normalized keyword term-freq sets of c vs each chosen, max over chosen),
  λ_sim default 0.25. Semantic-free: exact-term overlap only.
- `gap_pen` = λ_gap · clamp((preferred_gap − actual_gap)/preferred_gap, 0, 1), λ_gap default 0.15, with
  `preferred_gap` default 2× clip duration. Prefer spacing.
- All λ and enabler flags in config (`scoring.ranking.*`).
- Every selection stores `gain_note` explaining which penalty was dominant, so `explain` on a ranking result
  shows why a top-6 candidate was rejected.

**Scale (ADR-017, pinned by Sprint 6):** penalties are λ·ratio applied in **score-units on the 0–100 total
scale** (i.e. ×100), so a fully overlapping clip loses its whole score and `min_margin` is directly
comparable to a candidate's `total`. `ov_pen` sums overlap seconds over all chosen (capped at 1.0 ratio),
`sim_pen` takes the max Jaccard over chosen (token sets from the `keyword_density` term's `window_words`),
`gap_pen` measures the gap to the *nearest* chosen interval. `hard_min_start_gap` is a hard exclusion
(recorded, not scored). Ties resolve by earliest start, then stable id (ARCHITECTURE.md §7). `clipper rank`
writes `ranking.json` with the selected top-N (per-pick gain decomposition + `gain_note`) and the full
per-step marginal-gain decision log (`decisions[]`), so a dropped candidate is always attributable.

Alternative considered: global-optimal DP over the same cost. Rejected for MVP — greedy is O(n·k) vs DP space
growth, and its decisions are trivially attributable. A DP can replace it later behind the same interface.

## 8. Evaluation method (how we'll know it works)

The scoring engine ships with a **body of labeled fixtures** (synthetic + tiny real clips, curated by hand):
- `good/poor` labels per candidate, drawn from the scoring hypotheses.
- CI gates: on each fixture, precision/recall of "engine-picked top-3 vs human-labeled good" is reported.
  The threshold is informational first (no hard gate until labels grow), but deterministic — same numbering
  on every run.

This turns "is the scoring good?" into a measurable, versioned regression question instead of taste.
See TESTING.md.