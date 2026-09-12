# Signals

Every signal we extract, its hypothesis, how it maps into scoring, and — crucially — where that hypothesis
breaks. Format per signal: `signal → hypothesis → scoring effect → limitations`.

Not every measurable signal is an indicator of "interestingness". The `scoring effect` column is the only
place a signal may influence a score, and each one is individually disableable in config.

## 1. Audio signals

### RMS / energy (windowed, 50 ms)
- Hypothesis: sustained audible content is required; consistently near-silent windows are dead.
- Scoring effect: `audio_energy` sub-score — normalized mean window energy vs. the video's own 95th
  percentile (self-calibrating, so it works across quiet and loud sources without absolute dB targets).
- Limitations: music beds have high energy but low speech; a screaming segment ≠ a hook. Energy alone
  cannot and does not rank content.

### Loudness change / sudden energy change
- Hypothesis: an abrupt energy rise or fall at a window edge marks emphasis, laughter, applause, or a
  transition — the "punch" moments.
- Scoring effect: feeds `hook` sub-score (energy burst in first ~2 s of a candidate) and `pacing`
  (distribution of bursts).
- Limitations: mix/mastering differences dominate; a level change is not a semantic event. Treated as a
  weak, bounded signal (capped contribution).

### Peaks
- Hypothesis: clipping/very hot peaks correlate with poorly-mixed content.
- Scoring effect: small `penalty` when peak fraction is high.
- Limitations: modern loud content is heavily limited by design; only used as a mild quality guard, never a rank driver.

### Silence duration & pattern
- Hypothesis: dead air inside a candidate is bad; clean silence at a *boundary* is good (it means the cut
  lands where speech stops).
- Scoring effect: `leading_silence`/`trailing_silence` penalties (dead air ≤ 0.4 s at edges is tolerated,
  beyond is penalized); long internal silence → `dead_air` penalty; silence *boundaries* enable clean cuts.
- Limitations: pausing for thought is legitimate in lectures; threshold-based silence is blind to
  "dramatic pause" intent.

## 2. Transcript signals (from STT word timestamps)

### Word timestamps
- Hypothesis: word-level timing is the ground truth for everything below; everything is derived from it.
- Scoring effect: none directly — it powers speech density, rate, cadence, captions.
- Limitations: alignment jitter on noisy audio; whisper word `t0/t1` spans are estimates.

### Sentence boundaries & punctuation
- Hypothesis: sentences are the natural cut unit and the unit of "completeness".
- Scoring effect: `completeness` sub-score (candidate start/end on a sentence boundary), candidate
  generation alignment. Punctuation quality is the fragile link — our sentence grouping rules stand in for
  grammar, and are unit-tested against fixtures.
- Limitations: whisper's punctuation is inferred, not grammatical; code-switched/Indonesian casual speech
  breaks typical matching.

### Sentence length
- Hypothesis: a short declarative "hook line" inside the window's first seconds is a good opener; a wall of
  text (long unbroken sentences) hurts watchability.
- Scoring effect: `hook` (short first sentence) and `sentence_quality`.
- Limitations: length is a proxy; a long first sentence can be genuinely strong. Kept as a weak term.

### Word density / speech rate (WPM)
- Hypothesis: 140–190 WPM is comfortable; monotone slow or impenetrably fast is harder to watch.
- Scoring effect: `speech_density` + `pacing` (banded, non-monotonic).
- Limitations: natural variation is huge; per-speaker baselines (estimated from the whole video) are used to
  relativize. Banding softens the edges.

### Pause patterns / cadence
- Hypothesis: rhythmic speech with clean pauses is watchable; erratic micro-pauses signal flubbed speech.
- Scoring effect: `pacing`, small.
- Limitations: cross-speaker norms differ; only gross outliers are penalized.

### Question & exclamation patterns
- Hypothesis: questions ("how to", "why", "did you know") and exclamations are engagement hooks.
- Scoring effect: `hook` sub-score (question-mark ending early in window, exclamation patterns, WH-word
  sentence starts from a config list).
- Limitations: rhetorical questions are common in lecture content; term-list based, no semantics.

### Repeated words / self-correction
- Hypothesis: adjacent repeated words ("the the", "um um", stutter) inflate flubbed-speech odds.
- Scoring effect: small `penalty` for adjacency-repeats. Same-word-across-sentences is *not* penalized
  (that's emphasis, legitimate).
- Limitations: cohesive devices repeat legitimately; penalty deliberately tiny.

### Configurable hook phrases
- Hypothesis: in curated domains ("jangan lupa subscribe", "yang perlu kamu tahu", product mentions)
  known phrases are deliberate moments.
- Scoring effect: `hook`, matched on normalized text (lowercase, alnum-only) with word-boundary matching.
- Limitations: it's a blind term list — yields false positives, so a phrase matched anywhere outside the
  first ~30 % of the clip is capped at half contribution.

### Keyword density (term-list, deterministic)
- Hypothesis: a config-supplied keyword/domain list marks topical relevance.
- Scoring effect: `keyword_density` (normalized hits per minute, bounded).
- Limitations: **count-based term frequency only — no semantics**. "apple" ≠ "Apple". This is a feature:
  deterministic and explainable, but scope-limited; it never overrides completeness/audio.

### Beginnings/ends completeness
- Hypothesis: a clip that starts before the thought and ends mid-word is unwatchable; a clip that starts at a
  thought's beginning and lands on its end is fine on its own.
- Scoring effect: `completeness` (already covered via sentence boundary alignment) + `misaligned_end`
  penalty when whitepace-gap-to-boundary is small but boundary is missed.
- Limitations: depends entirely on sentence grouping quality.

## 3. Visual signals

### Scene changes
- Hypothesis: scene cuts are organic attention resets; scene *density* in a clip is a watchability signal —
  too high = strobing cut-up content, too low = static talking-head with no movement.
- Scoring effect: `visual_activity` (banded, non-monotonic: a mid band scores best).
- Limitations: cuts ≠ interesting; for a talking-head show, cuts are edits, not content. Which is exactly why
  the band is tuned conservatively and visual weight is small.

### Frame difference / motion intensity
- Hypothesis: persistent micro-motion (gestures, camera sway, on-screen movement) keeps a clip alive; motion
  near a hook compounds engagement.
- Scoring effect: `visual_activity` + `hook` (motion burst at start).
- Limitations: motion ≠ content; busy but meaningless backgrounds produce false "activity". Capped.

### Face presence / count / position / size (POST-MVP)
- Hypothesis: a face is the strongest "subject" anchor for both scoring and reframing; face size/centerness
  correlates with a watchable frame.
- Scoring effect (when enabled): `face_presence` sub-score; reframe focus point from face centroid.
- Limitations: not in MVP — it's the most expensive optional signal and reframing only needs the centroid,
  which we can derive later without touching the scoring interface. Deliberately deferred; the interface for
  `visual_activity` is prepared so a face signal plugs into the same slot.

### Subject position (POST-MVP)
- Hypothesis: the human subject keeps a consistent screen area; reframing can follow it.
- Scoring effect: none — reframing target only, never a rank driver.
- Limitations: without detection there is no subject; degenerate to center.

## 4. Signal→score wiring summary

| Signal | Sub-score | Default weight | Signal group |
|---|---|---|---|
| window energy | audio_energy | 0.09 | audio |
| source loudness (info only) | — | — | audio |
| peaks | penalty | — | audio |
| speech presence ratio | speech_density | 0.13 | transcript |
| WPM band | pacing | 0.10 | transcript |
| question/exclamation/hook phrase/energy burst/motion burst | hook | 0.15 | mixed |
| sentence boundaries aligned | completeness | 0.20 | transcript |
| scene density band + motion | visual_activity | 0.10 | visual |
| keyword hits/min | keyword_density | 0.10 | transcript |
| sentence length band | sentence_quality | 0.06 | transcript |
| silence at edges, dead air, mid-sentence, mid-word, flubs | penalties | −cap | mixed |

Per-signal weights, thresholds, and on/off flags are all in CONFIGURATION.md. The mapping table above is the
canonical wiring; SCORING_ENGINE.md defines the math.