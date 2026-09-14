# Dependencies

Evaluated for **Arch Linux x86_64** (this machine: Archcraft, ffmpeg 9.0.1-4). For each: function, rationale,
resource usage, install, license, required/optional, alternatives.

Principle: **as few as possible, each with a job.** We intentionally do *not* take OpenCV/librosa/MediaPipe
into the MVP even though they're popular — see the "rejected" table.

Policy on drift: exact versions are recorded in `manifest.json` on every run. A tool version change is
detected and flagged rather than silently changing output.

## 1. Required (runtime)

### ffmpeg + ffprobe
| | |
|---|---|
| Function | All media decode/encode: PCM extraction, low-res frame pass, scene/motion metrics, `subtitle` burn-in (libass), trim/crop/scale, encode. ffprobe for metadata. |
| Rationale | Single powerful local tool covers analysis + rendering; filter set confirmed present (`scdet`, `signalstats`, `ebur128`, `silencedetect`, `loudnorm`, `subtitles`, `crop`/`scale`); no Python binding needed because we shell out to a pinned arg set. |
| Resource | Decode-bound: low-res gray pass ~negligible; render pass is the main CPU consumer (minutes per clip, x264 medium). |
| Install (Arch) | `sudo pacman -S ffmpeg` |
| License | LGPL-2.1+ (built with optional GPL parts: libx264/libx265/shared → the Arch package is GPL-compatible build). |
| Required? | **Yes** — no fallback; `clipper verify-env` is uncompromising about it. |
| Alternative | LibAV / gstreamer (unnecessary divergence), MoviePy (thinner, slower, wraps ffmpeg anyway). |

### Python ≥ 3.12 (dev + glue) + numpy
| | |
|---|---|
| Function | Orchestration, numpy window math for audio/motion features, text processing, captions, scoring. |
| Rationale | Fastest path to correct+testable signal math and CLI; hot paths are native (ffmpeg, whisper). Python is 0.001 % of CPU. |
| Resource | CGI-level; arrays are float32 over short media (a 1 h mono 16k stream ≈ 115 MB → trivial). |
| Install (Arch) | system `python` (3.14 present) + `python-numpy` (pacman) or uv-managed virtualenv with numpy wheel. |
| License | Python: PSF-2.0; numpy: BSD-3. |
| Required? | **Yes** (analysis math); binaries installable via `uv`. |
| Alternative | Rust/C++ (see §5 language trade-off), node (weaker numeric+STT ecosystem for this). |

### whisper.cpp (`whisper-cli`)
| | |
|---|---|
| Function | Local speech-to-text with word-level timestamps → transcript input for candidates/captions/scoring. |
| Rationale | Single dependency-free native binary; no model conversion step; greedy decode (`-bs 0`, `-t 0`) is deterministic for a fixed build; MIT-compatible. **Format reality (ADR-013):** ≥ 1.9.x JSON has no `words[]`/`t0,t1` — timestamps are per-token `t_dtw` (centiseconds), emitted only with `-nfa --dtw <preset> -ojf` (flash-attn defaults ON and disables DTW). Word spans are reconstructed from BPE tokens by the bridge. |
| Version tested | whisper.cpp **1.9.4-dev**, `ggml-small.bin` (`sha256 1be3a9b2…ea987b`, 488 MB). A `<model>-dtw` preset is required and matched to `tiny/base/small/medium` model sizes (no `large` preset). |
| Resource | Dominant cost. `ggml-base` ≤ ~1× realtime; `ggml-small` ~1.5–3×; `ggml-medium` ≫ (avoid on CPU for MVP). RAM: ~1–3 GB depending on model. |
| Install (Arch) | AUR `whisper.cpp` (installs `whisper-cli`); or build once locally — `cmake`/`make` per the project's own instructions. Model `.bin` fetched once via `clipper fetch-model` (HuggingFace, sha256 recorded) into `model/`. |
| License | MIT (code); model weights inherit OpenAI Whisper license (Apache-2.0-compatible data usage, redistributable). |
| Required? | **Yes for the full transcript path. Degradable**: if absent → audio-only scoring + silence/scene candidate generation still works (`--no-transcript`), fully functional for energy-driven clips. |
| Alternative | faster-whisper (pip, CTranslate2 models; easier pip install, adds Python runtime dep — keep as post-MVP engine option behind the `transcript.engine` key). |

## 2. Optional

### ImageMagick (`magick`)
| | |
|---|---|
| Function | Contact sheets / thumbnails montage → previews. |
| Rationale | Already installed; trivial `montage`. |
| Install | `sudo pacman -S imagemagick` |
| License | ImageMagick License (permissive). |
| Required? | No — `report` works without it (HTML-only previews fallback). |

### ffmpeg `loudnorm` (dynamic mode)
| Function | 2-pass EBU R128 normalization (opt-in profile). |
| Rationale | *Not* default — dynamic loudnorm is soft/version-dependent and fights determinism. Default = static gain from measured loudness (fully deterministic). |
| License | LGPL (filter within ffmpeg). |

## 3. Rejected for MVP (explicitly evaluated)

| Tool | Why rejected | Revisit when |
|---|---|---|
| OpenCV | Needed only for face/motion if we want it anyway; the ffmpeg-based scene+motion signals cover MVP visual needs with zero install. Its `dnn` face detectors are also non-ideal for portrait (they're SSD-based). | Visual/reframe milestone needs real subject tracking. |
| MediaPipe (face mesh) | High install weight (protobuf, bazel-built deps on Arch), needs pip runtime; output not naturally "one centroid". | Only for face-reframing milestone; prefer OpenCV haar as MVP-of-that, MediaPipe only if quality requires. |
| librosa | Powerful, but numpy already covers RMS/energy/silence; librosa would add dozens of deps for features we compute in 60 lines. | If spectral features (e.g. onset/music mode) are ever needed — music profile. |
| Torch / ML libs | No model in the scoring path; holding a framework opens the door to "just add a model" creep. | Only if a *justified supporting* signal is adopted with a written rationale. |
| faster-whisper as default | Adds Python C-extension runtime + CTranslate2 models; whisper.cpp is leaner and per-binary deterministic. | If whisper.cpp maintenance/staleness becomes a problem. |

## 4. Dev tooling

| Tool | Role | Arch |
|---|---|---|
| `uv` | env + lock (`uv sync`, `uv tool install`) | `curl -LsSf https://astral.sh/uv/install.sh | sh` |
| `ruff` | lint+format | `dependency-groups.dev` via uv (ADR-012) |
| `pytest` + `pytest-cov` | tests | `dependency-groups.dev` via uv (ADR-012) |
| `typer` + `rich` | CLI + pretty output | runtime deps via uv |
| `pydantic v2` | config/contract validation | runtime dep via uv |
| `PyYAML` | config-file parsing (ADR-011) | runtime dep via uv |

Runtime Python deps = numpy, pydantic, PyYAML, typer, rich (binaries ffmpeg/whisper.cpp are not pip). Dev tooling
(ruff/pytest/pytest-cov) lives in a PEP 735 `[dependency-groups] dev` block: installed by default with `uv sync`,
skipped in production with `uv sync --no-dev`.

## 5. Language trade-off (why not Rust)

MVP correctness speed matters more than CPU speed; the two native tools (ffmpeg, whisper.cpp) already do the
heavy work, so Python's 3× overhead on glue is below noise. Rust would buy wall-time on the numpy math
(microseconds total) and static distribution (nice, not needed for a local tool), at the cost of slower
iteration on the riskiest part — sentence grouping, boundaries, scoring. **Decision: Python, with `score/`
functions kept pure** so a future Rust port of scoring is mechanical. Recorded in DECISIONS.md.

## 6. Offline/networking contract

- Analysis/scoring/rendering: **zero network**.
- Only network op: one-time model download (whisper ggml `.bin`) + optional `uv sync` for dev. `verify-env`
  never phones home.
- "Local-first" is enforced by tests running in a network-sandboxed CI step (no HTTP in `scoria/` except the
  model-fetch helper, which is a separate `scoria fetch-model` command).