# PRD — Deterministic Video Clipper (`scoria` / `clipper`)

- Status: DRAFT
- Last updated: 2026-09-12
- Moving parts that can change: package name, CLI verb names, file layout inside a project directory.

## 1. One-paragraph summary

A **local-first, deterministic CLI** that takes a video (short/long-form), extracts measurable signals
from audio, transcript and video frames, splits it into candidate segments, scores every candidate with
transparent rule-based heuristics, ranks them, and renders the best ones as **9:16 vertical clips with
burned-in captions** — all offline, no cloud APIs, no LLM in the scoring path.

Guiding principle: **signal extraction + deterministic heuristics + configurable scoring + local media
processing.** This is an engineering problem (measuring signals and combining them reproducibly), not an
"AI that knows what goes viral".

## 2. Personas

| Persona | Need |
|---|---|
| Content creator (podcast/interview/lecture) | Turn one long recording into several share-ready vertical clips quickly |
| Batch/scripting user | Run analysis once, tweak config, re-render many videos without re-analyzing |
| Developer/contributor | Understand *why* a clip was picked without reading source |

## 3. Goals / Non-goals

### Goals (MVP)
1. `clipper video.mp4` → analyze, segment, score, rank, render top-N vertical clips with captions.
2. Every choice explainable at CLI level (`clipper explain <id>`).
3. Fully offline. Whisper models are the only downloaded artifact (seen once, cached).
4. Deterministic for fixed input + config + model (see ARCHITECTURE.md §Determinism).
5. Analysis, scoring, ranking, rendering cleanly separated — user can `analyze → inspect → edit config → render`.

### Non-goals (explicitly out of scope)
- Generative AI, LLM-based scoring, automatic content rewriting or re-voicing
- Cloud APIs / paid services / vendor lock-in
- Thumbnail generation, title generation, hashtags
- Social media publishing
- Web dashboard, multi-user, auth, cloud storage
- Semantic "viral-potential" prediction

These are rejected because they each violate determinism/explainability/local-first. Revisit only if a
later milestone explicitly asks for them with a concrete deterministic argument.

## 4. Target platform

Primary: **Arch Linux x86_64, CLI.** Confirmed on this machine: Archcraft (Arch-based), ffmpeg 9.0.1
(pacman `ffmpeg`), Python 3.14.7. Secondary: other Linux distros. Windows/macOS not a goal.

Tooling must work from `zsh`/`bash`, be pipeline-friendly (`--json` flags, stable file layout), and
consume/reproduce a project directory without re-analysis.

## 5. Core user flows

```
clipper video.mp4                       # one-shot: analyze + rank + render top clips
clipper analyze video.mp4 -o proj/     # analysis.json + candidates + scoring breakdowns
clipper rank proj/analysis.json --top 5
clipper render proj/ranking.json -o proj/clips
clipper explain proj/analysis.json clip-03
clipper report proj/analysis.json      # previews + report.html
```

Full spec in CLI_SPEC.md. The one-shot command is a thin composition of the same pipeline used by the
step commands — the step commands are always available for the `analyze → inspect → tune → render` loop.

## 6. Feasibility analysis (honest)

### Where deterministic scoring works
- **Talking-head / interview / podcast / lecture** with one-ish continuous speaker: transcript is reliable,
  boundaries fall on silence + sentences, scoring cues (hooks, completeness, pacing) are meaningful. **Best fit.**
- **Let's-play / gaming with live commentary**: workable if the narration is continuous and scene changes map
  to real moments; hook detection can leverage energy + scene bursts. Decent fit with the `gaming` profile.
- **News-style / structured vlogs**: good, because structure gives clean sentence/scene boundaries.

### Where it struggles / fails
- **Music videos / instrumental or beat-driven content with no speech**: transcript pipeline is useless;
  only audio energy + visual salience remain. Requires a separate "music mode" (future, not MVP).
- **Bi-lingual / code-switched speech** (common in Indonesian content): Whisper still transcribes, but
  punctuation quality drops; sentence boundary detection degrades.
- **Overlapping speakers / heavy background noise**: transcript word timings become noisy; silence
  boundaries vanish. Don't promise anything here for MVP.
- **Montage/B-roll heavy video where the story is visual, not spoken**: signals exist but the model has no
  notion of "story". Will rank on energy, not narrative. Documented limitation, not bug.

### External-tool reality check (this machine)
- ffmpeg/ffprobe 9.0.1 **present** with everything we need: `scdet`, `signalstats`, `ebur128`,
  `silencedetect`, `loudnorm`, `subtitles` (libass), `crop`, `scale`; x264/x265/aac/libopus encoders.
- Whisper: **not installed** (neither whisper.cpp nor faster-whisper). It is the one required component
  missing; install path documented in DEPENDENCIES.md. If STT is unavailable, the pipeline must degrade
  gracefully to audio-only scoring (kept as a first-class fallback, not an afterthought).
- Python 3.14 available; `uv`, `ruff`, `pytest` not yet installed (bootstrap in Sprint 0).

### Speed / resource reality (CPU-only, x86_64)
- Whisper decode is the dominant cost: `ggml-base` ≈ 1× realtime or less on modern CPU; `ggml-small`
  ≈ 1.5–3× realtime; `ggml-medium` substantially slower (often > 10× realtime). Recommendation is
  `small` for quality, `base` for MVP iteration loop.
- ffmpeg analysis (audio PCM pass + low-res grayscale frame pass at ~4 fps) is cheap: a few % of whisper time.
- Rendering top-5 60s clips at 1080×1920 with x264 `preset=medium` is minutes, not hours.

### What is hardest
1. **Clean sentence boundaries from Whisper output** — whisper.cpp gives word timings, but sentence grouping /
   punctuation inference needs our own rules. This is the single biggest quality lever and the most fragile.
2. **Candidate generation that doesn't cut mid-sentence** — a fixed-window approach fails; the boundary-based
   algorithm in §ARCHITECTURE is the core risk to test earliest.
3. **Vertical reframing** — center crop is trivial and fully deterministic; face-tracking reframing is a
   *trajectory-smoothing* problem (EMA/One-Euro) more than a detection problem. Kept out of MVP on purpose.

### MVP feasibility verdict
**Achievable as a genuinely useful v0** for talking-head/podcast/lecture media. For visual/beat-driven media
we ship a documented "energy mode" later — the architecture (modular signal components) leaves that door open
without bending the scoring core.

## 7. MVP scope (explicit)

The video → clips loop, with these components:

| Component | Status |
|---|---|
| Ingest (ffprobe metadata, validation) | ✅ MVP |
| Audio analysis (RMS/energy, silence, loudness via numpy + ffmpeg PCM) | ✅ MVP |
| Speech/transcript (whisper.cpp bridge, word-level timings, sentence grouping) | ✅ MVP, **degradable to off** |
| Visual analysis (scene change + motion intensity only) | ✅ MVP |
| Segmentation + candidate generation (boundary-driven windows) | ✅ MVP |
| Scoring engine (single deterministic formula, all sub-scores, penalties) | ✅ MVP |
| Ranking with temporal/topic diversity | ✅ MVP |
| Captions (SRT + ASS word-karaoke, burn-in) | ✅ MVP |
| Reframing **center-only** (no face tracking) | ✅ MVP |
| Render (trim/crop/scale/subs/static-gain loudness/encode) | ✅ MVP |
| Report + previews + contact sheet + `explain` | ✅ MVP (minimal: assets + HTML) |
| Face detection, face-based reframing, motion-based reframing | ❌ Post-MVP |
| Multi-speaker diarization | ❌ Post-MVP (exploratory) |
| Music/beat-driven "energy mode" | ❌ Post-MVP |
| Thumbnails, titles, publishing | ❌ Non-goal |

## 8. Success criteria (MVP)

1. `clipper video.mp4 --top 3` produces 3 valid 1080×1920 MP4s with burned-in captions for a 5+ minute
   talking-head video, in a single command.
2. Re-running `clipper analyze` on the same input+config+model produces **byte-identical** JSON artifacts.
3. `clipper explain clip-02` shows a full numeric breakdown, both for a chosen clip and a rejected candidate.
4. Ratio of "clean cuts" (starts/ends on sentence or scene boundary, no mid-word) ≥ 90% on fixture media.
5. `analysis` → `render` can be re-run without re-analysis after editing only scoring weights.
6. All runtime logic is offline; no network access at runtime except one-time model download.
7. A unit-testable, injectable architecture where every scoring function takes a plain feature vector
   and returns a plain breakdown.

**Real-footage validation (manual, non-CI):** success criteria 1 and 4 are also spot-checked against real
captures kept in `sample raw/` (untracked, git-ignored — e.g. a gamer live-streaming recording), via manual
`clipper run --top 3` runs plus clean-cut / burn-in inspection. CI stays synthetic-only so the pipeline never
couples to any one creator's media.

## 9. Risks (top)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sentence boundaries from Whisper are wrong | High | High | Own sentence-grouping rules + unit fixtures; degrade gracefully; expose boundary editing via `analysis.json` |
| Whisper non-determinism across builds/CPUs | Medium | Medium | Pin model hash + greedy decode; document scope of determinism (ARCHITECTURE §Determinism) |
| "Best 5 clips are all from the same minute" | Medium | High | Diversity penalties in ranking stage (SCORING_ENGINE §Ranking) |
| Over-engineering territory creep | Medium | High | Non-goals list is enforced by sprint scope; PR review checklist |
| STT install friction on fresh Arch box | Medium | Medium | AUR/package docs + graceful audio-only fallback |

## 10. Config & profiles

Everything numeric is configurable via YAML; built-in profiles `podcast | gaming | lecture | interview |
talking-head` override defaults (see CONFIGURATION.md). Profiles are deltas over a `default` profile — no
behavior is hardcoded in code paths.

## 11. Output contract

`clipper` writes a **project directory** (default `<video>.scoria/`, overridable) containing structured JSON
artifacts (stable schemas, sorted keys, fixed float precision), `clips/`, `captions/`, `previews/`,
`report.html`. Everything needed to re-score or re-render is in the JSOM. Details in ARCHITECTURE.md
§Artifacts.