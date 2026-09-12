# Configuration

Single YAML file, validated by pydantic at load. Merge order: `defaults < profile < CLI overrides`.

No behavior is hardcoded in code paths — if a number exists in the scoring/segment/reframe/render domain it
has a config key. Unknown keys are errors (exit 2), not silent ignores.

Location search: `./scoria.yaml`, `~/.config/scoria/config.yaml`, `--config FILE`. Profiles are selected by
`--profile` or `config: {profile: name}`. A profile is a partial override map merged on top of defaults.

## 1. Full schema (defaults shown)

```yaml
version: 1

project:
  dir: "auto"                 # "<video>.scoria/" unless overridden
  overwrite: false
  keep_temp: false
  temp_dir: "auto"            # work dir for PCM/frames/whisper json

media:
  min_duration: 8.0           # seconds; shorter input → hard error
  max_duration: 7200.0        # beyond this warn: STT cost explodes
  analyze_audio_rate: 16000   # Hz for PCM extraction
  frame: {fps: 4, width: 64, height: 36, pix_fmt: gray}

input:
  video_stream: "auto"        # "auto" | index; error if absent

transcript:
  enabled: true
  engine: whisper.cpp         # whisper.cpp | off (faster-whisper = post-MVP)
  binary: whisper-cli         # absolute path overrides PATH lookup
  model: "model/ggml-small.bin"
  model_sha256: ""            # if non-empty, verified at startup
  language: "auto"            # "auto" | "id" | "en" | …
  greedy: true                # greedy decode (-bs 0, -t 0) for determinism
  threads: 4                  # pinned; determinism + record in manifest
  segment_from_whisper: true  # use whisper segment breaks as sentence hints
  sentence:                  # our rule-based sentence grouping (SIGNALS.md §2)
    max_gap_seconds: 1.2      # merge words across gaps below this
    min_sentence_words: 2
    force_punctuation: true   # infer . ! ? at segment ends
  hooks:                     # hook phrase list (matched normalized, word-boundary)
    phrases: ["yang perlu kamu tahu", "jangan lupa subscribe", "kunci",
              "rahasia", "tips", "cara", "ternyata"]
  keywords:                 # keyword density list
    terms: ["kunci", "tips", "cara", "tutorial", "review", "harga"]

audio:
  window_ms: 50
  analyze_start: 0.0         # only analyze [start, end] when set
  analyze_end: 0.0
  silence:
    threshold_db: -35
    min_duration: 0.35       # silence shorter than this is not a boundary
    edge_tolerance: 0.4      # silence at window edge ≤ this → no penalty
    dead_air: 1.5            # internal silence ≥ this → dead_air penalty

segment:
  min_duration: 20.0
  max_duration: 60.0
  preferred: {min: 35, max: 45}
  scene_detection_threshold: 0.35     # scdet-style scene cut threshold
  max_candidates_per_start: 2
  hard_cut_margin: 0.25               # grace when sentence > max_duration (seconds)

scoring:
  version: "1.0.0"
  renormalize_disabled: true
  weights:
    audio_energy: 0.09
    speech_density: 0.13
    pacing: 0.10
    hook: 0.15
    completeness: 0.20
    visual_activity: 0.10
    keyword_density: 0.06
    sentence_quality: 0.06
    face_presence: 0.00
  terms:
    energy_bounds: {low: 0.15, high: 0.75}
    speech_bounds: {low: 0.30, high: 0.85}
    pacing_band: {lo: 0.85, hi: 1.35}     # relative to video baseline
    wpm_base_window: 30.0
    visual_band: {soft: 1.5, hard: 6.0}   # changes/min trapezoid
    keyword_band: {low: 0.5, high: 3.0}   # hits/min
    sentence_band: {wlo: 6, lo: 9, hi: 18, whi: 22}
    hook_first_fraction: 0.30             # phrase must be in first X of clip for full credit
    hook_max_first_sentence_words: 12
    hook_short_first_sentence_words: 8
    hook_burst_multiplier: 3.0            # first-2s energy/motion vs clip mean
    hook_burst_value: 0.8
  penalties:
    config:
      leading_silence: true
      trailing_silence: true
      dead_air: true
      mid_sentence_start: true
      mid_word_end: true
      low_energy_tail: true
      flub_repeats: true
      peak_clipping: false
    caps:
      edge_silence: 0.10
      dead_air: 0.15
      mid_sentence: 0.15
      mid_word: 0.20
      tail: 0.05
      flub: 0.05
      clip: 0.02
    total_cap: 0.35
  ranking:
    enabled: true
    min_margin: 20.0          # G(c) below this → stop selecting
    lam_overlap: 1.0
    lam_similarity: 0.25
    lam_gap: 0.15
    preferred_gap_factor: 2.0  # × clip duration
    hard_min_start_gap: 0.0

captions:
  enabled: true
  format: [srt, ass]          # always both sidecars
  burn_in: true               # render with subtitles filter
  chars_per_line: 42
  max_lines: 2
  max_duration: 4.5           # max caption on-screen seconds
  min_word_count: 1
  prefer_sentence_breaks: true
  ass_style:
    name: Caption
    font: "DejaVu Sans"
    font_size: 58
    primary_colour: "&H00FFFFFF"
    outline_colour: "&H00000000"
    outline: 3
    shadow: 1
    margin_v: 160             # safe-area: bottom of vertical frame
    karaoke_words: true       # {\k...} per word
  safe_area_bottom: 0.25      # fraction of frame height reserved for captions

reframe:
  mode: center                # center | faces(post-MVP) | target
  focus: {x: 0.5, y: 0.5}     # used by mode: target
  blurbad_threshold: 1.78     # source ar > this → blur-pad instead of deep crop
  output: {width: 1080, height: 1920}
  smooth: {ema_alpha: 0.10, window_s: 0.5}   # post-MVP, unused by center
  even_dim: true              # crop dims rounded to even for chroma

render:
  video:
    codec: libx264
    crf: 19
    preset: medium
    pix_fmt: yuv420p
    faststart: true
  audio:
    method: static_gain       # static_gain | loudnorm(2-pass, opt-in)
    target_lufs: -16.0
    target_peak: -1.5
    lra: 11.0
  threads: 4
  overwrite_output: true      # isolated to temp then renamed atomic

report:
  preview_width: 320
  per_candidate_strips: 5     # contact sheet frames per clip
  include_score_table: true
```

## 2. Profiles

Profiles are deltas. `clipper --profile gaming` loads the same schema with partial overrides.
Intent of each (validated by the fixture set in SCORING_ENGINE §8, not by feel):

| Profile | Moves compared to default | Intended media |
|---|---|---|
| `podcast` | speech_density +, visual_activity −, audio_energy +, keyword − | long-form audio-first talk |
| `lecture` | completeness +, hook −, pacing − (slower cadence ok), speech_density + | teaching/screencast |
| `interview` | sentence_quality +, hook + (questions), audio − | structured Q&A |
| `gaming` | visual_activity +, hook + (bursts), speech_density −, keyword − | let's-play w/ commentary |
| `talking-head` | audio_energy −, visual_activity −, completeness + | close-up monologue |

Each profile, when selected, is added to `manifest.json` so downstream users can see exactly what changed.

## 3. Validation rules (a selection)

- `scoring.weights` values ≥ 0; renormalized enabled sum ∈ [0.99, 1.01] or config load error.
- `segment.min_duration ≤ preferred.min ≤ preferred.max ≤ max_duration`.
- `captions.max_duration ≥ (chars_per_line·max_lines)/(wpm/60)` — i.e., caption must be physically
  readable; otherwise error with the computed minimum.
- `reframe.output` must be ≥ 2× even dims, orientation 9:16 exactly (`w/h == 9/16`).
- `audio.silence.min_duration ≤ segment.min_duration/10` sanity.
- Unknown key → error. `transcript.enabled: false` auto-disables speech-dependent scoring terms with a
  warning and sets `renormalize_disabled: true` behavior (SCORING_ENGINE §5).

## 4. Batching / scripting

Config files are valid YAML and may contain the same keys as CLI flags; CLI wins. For batch runs, generate
one config per input from a template (e.g. `scoria config write-defaults > base.yaml`, then override
`keywords.terms` per video). Per-video keywords are the primary use case for batching.