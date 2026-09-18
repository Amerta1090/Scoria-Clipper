# Testing

Strategy: determinism-first, fixture-driven, layered. No video required to test the core; full-media
integration tests are opt-in and env-gated.

Test layering (bottom ↑) mirrors the architecture: pure functions → modules → pipeline → CLI.

## 1. Layers

| Layer | Scope | Runs in CI |
|---|---|---|
| L0 unit | `score/` sub-score functions, `segment/` boundary+window math, `captions/` line builder, serialization contract | always, fast |
| L1 module | `audio/` & `visual/` feature extraction against tiny generated media; `transcript/` against fixture JSON (no STT) | always |
| L2 pipeline | analyze→score→rank on synthetic fixtures, golden JSON diff | always |
| L3 integration | render: real ffmpeg trim/crop/scale/subs/encode → ffprobe assertions | gated (ffmpeg+libass present ~ always here) |
| L4 determinism | two full `run`s → sha256 corpus comparison (tests/test_run.py) | always (archlinux job) |
| L5 e2e CLI | `clipper` subprocess commands incl. exit codes, `--json`, `verify-env` | always |

## 2. Deterministic fixtures

`tests/fixtures/` (all generated, no copyrighted media):

- **`synthetic.mp4`** — generated at test-time by ffmpeg `lavfi` (`testsrc2` + `sine` tones) + optional
  `espeak-ng` spoken track (if installed) so it carries real words and silence gaps at known times.
  Generation script lives next to the fixtures; deterministic by construction.
- **`transcript_small.json`** — frozen whisper.cpp 1.9.4 `-ojf` shape (ADR-013/014: top-level
  `transcription[]` with per-token `t_dtw` timestamps, no `words[]`) encoding known sentences,
  pauses, a question opener, and a mid-sentence trap. Drives L0 parse/normalize/group goldens +
  L1 transcript tests without STT. The real bridge (decode → whisper-cli → parse) is a separate
  smoke test gated on `SCORIA_WHISPER_BIN` + `SCORIA_WHISPER_MODEL` (skipped otherwise).
- **`analysis_small.json`** — complete hand-built analysis (audio RMS series, silence list, scene list)
  so `segment/score/rank` run end-to-end with zero media tools at all.
- **Labeled candidates** (SCORING_ENGINE §8): `good.json`/`poor.json` per candidate as human labels;
  `score` regression reports precision/recall deterministically.

Every runtime JSON artifact in fixtures is checked against the **serialization contract** (sorted keys,
4-decimal floats) so golden diffs are byte-stable.

### 2.1 Real-video testing (manual, optional)

`sample raw/` holds **untracked, user-provided captures** (e.g. a gamer live-streaming recording) for manual
end-to-end runs — not part of CI. `.gitignore`d by design, so anything dropped there stays local.

Use it for what synthetic fixtures can't verify: real whisper decode + STT latency on a genuine talking-head
track, real sentence/scene boundaries feeding candidate cuts, burn-in quality, and the PRD §8 cold-start
(`clipper run --top 3`). Commands run against the capture in place — `clipper analyze "sample raw/<video>.mp4"
-c cfg -o <tmp project>` — with output treated as evidence, never as a committed golden.

## 3. What each core component must prove

- **score/** — property: given identical feature dicts → identical breakdown floats. Bounds: every
  sub-score ∈ [0,1]; total ∈ [0,100]; penalties capped. Renormalization sum ≈ 1. Golden: known candidates
  produce exact expected totals (fixture-pinned).
- **segment/** — boundaries dedupe+sort; candidate windows never < `min_duration` or > `max_duration`;
  complete-cut candidates flagged (no `mid_sentence`); hard-cut only when sentence exceeds `max`;
  O(boundaries) budget respected.
- **rank/** — overlap penalty math; greedy stop (margin); spacing; determinism of tie-break by start time.
- **captions/** — line widths ≤ `chars_per_line`; caption durations ≤ `max_duration`; SRT/ASS parse cleanly
  (round-trip via a tiny parse to re-extract timings); karaoke `\k` values equal word durations.
- **audio/ & visual/** — extraction on `synthetic.mp4` returns expected silence spans (we know the sine
  placement) and expected motion (testsrc2 change pattern). Noiseless → exact numbers.
- **project/** — artifact round-trip: serialize→parse→serialize = byte-stable; `manifest.json` records
  versions + config snapshot + SCORING_VERSION.
- **render/** — ffprobe of rendered clip: 1080×1920, `yuv420p`, duration ≠ start−end ±100 ms, audio stream
  present, captions text present in frame (checked via `libass` subtitle+a screenshot OCR-if-available,
  else presence of subtitle filter + sidecar file equality).

## 4. Determinism test (L4)

```
run pipeline (analyze→score→rank→captions only) on synthetic.mp4 twice
→ sha256 each artifact + sorted dump → assert identical sets
repeat with threads=2 and threads=4 → assert identical (pinned-thread independence for JSON)
```

Render determinism: x264 with fixed version+threads is deterministic upstream; the test renders the same
clip twice and asserts identical sha256 (stream-level). If an encoder genuinely can't be pinned, it is
marked non-deterministic in `manifest.json` and the test *documents* rather than fails — the JSON contract is
never allowed to break.

L4 variants (Sprint 12/13):
- **Gamer profile** (`--profile gaming`): full two-zone run twice → byte-identical corpus + clip streams;
  default center run stays the regression baseline.
- **Captions-on** (`transcript.enabled: true` + `transcript.path` → aligned golden fixture, no whisper
  binary): same two-run byte-identical corpus incl. SRT/ASS sidecars; `render.json.burn=True` when libass
  is present (burn-smoke: burned bytes ≠ bare-clip bytes), else `burn_sidecar_only` — still deterministic.

## 5. Degraded-mode tests

- STT off (`--no-transcript`): scoring renormalizes (sum ≈ 1), candidates from silence+scene only, no
  caption burn, `manifest.degraded=['transcript']`. Must not crash on any stage.
- No visual (`--no-visual`): visual_activity renormalized out, candidates from sentence+silence only.
- Both off: candidates from silence only, pure energy scoring. (This is the graceful floor.)
- libass missing: burn-in skipped, sidecars still written, warning in manifest.

## 6. CLI tests (L5)

- `clipper analyze → score → rank → render` happy path exit 0.
- `--json` output parses with `jq`/json.loads and contains expected keys.
- Bad config key → exit 2. Unknown flag → exit 2. Missing input → exit 1 with actionable text.
- `verify-env` on this machine passes and prints the exact versions used for reproducibility.
- `clipper explain clip-01 --json` emits a ScoreBreakdown identical to the one embedded in candidates.json.

## 7. CI

Stages: `uv sync` → `ruff check` → `ruff format --check` → pytest (L0–L5). CI image:
archlinux with `ffmpeg` (matches the L4 determinism target); ubuntu-latest is a future
breadth option. Network-sandboxed: pytest runs with no HTTP access (`block-network`
plugin) to enforce offline runtime. Optional: a scheduled/nightly L4 job on other
images is future work.

## 8. Coverage targets

- New scoring/segment/rank/caption logic: 100 % line coverage on those modules (they have no I/O, so this is
  cheap and meaningful).
- I/O modules (ingest/audio/visual/render): functional coverage via integration tests; line % advisory.
- `coverage` via pytest-cov, `fail_under=` set per package in pyproject.