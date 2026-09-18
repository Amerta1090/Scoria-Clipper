# scoria — Agent Operating Prompt

Saying **`prompt.md`** in any new session restores this working context: what the project is, which docs are
ground truth, the session protocol, commit rules, and the Definition of Done. Then read `SPRINT_STATUS.md`
for where work stopped.

## What this project is

Deterministic, local-first video clipping engine. CLI binary `clipper`, Python package `scoria`.
Target: Arch Linux, x86_64, CLI-first, offline.

- One command: `clipper video.mp4 --top 3` → ranked 9:16 vertical clips with burned captions.
- Two cut modes: `clipper run X` → 9:16 center crop (default); `clipper run X --profile gaming`
  → two-zone "gamer" layout (gameplay top + facecam bottom), same closed-form determinism.
- Captions need a transcript: real STT via whisper.cpp, or `transcript.path` (saved
  transcript-info JSON) for offline/deterministic runs — burn is byte-reproducible both ways.
- Stack: ffmpeg/ffprobe (media), numpy (signal math), whisper.cpp (STT), Python ≥ 3.12, uv (dev).
- Soul: **signal extraction + deterministic heuristics + configurable scoring + local media processing.**
  This is an engineering problem — measurable signals combined reproducibly — NOT an LLM wrapper, NOT a
  "viral predictor".
- EXPLICIT NON-GOALS (PRD §3): cloud/paid APIs, generative AI, automatic rewriting/re-voicing,
  thumbnail/title generation, social publishing, web dashboard, multi-user, auth, cloud storage.

## Ground truth (read in this order when you need detail)

`docs/`:
- `PRD.md` — requirements, feasibility (incl. where heuristics work/fail), MVP scope, success criteria, risks
- `ARCHITECTURE.md` — **layering is non-negotiable**: Analysis | Scoring | Ranking | Rendering never mix;
  module map, pipeline data-flow, artifact layout, determinism model
- `SIGNALS.md` — signal → hypothesis → scoring wiring + limitations
- `SCORING_ENGINE.md` — the exact formula: sub-scores, weights, penalties, ranking + diversity
- `CLI_SPEC.md` — command surface + examples
- `CONFIGURATION.md` — YAML schema, profiles, validation rules
- `DEPENDENCIES.md` — tool stack, Arch install, rejected tools (why)
- `TESTING.md` — test layers (L0–L5), fixtures, determinism test
- `ROADMAP.md` — milestones M0–M3 + guardrails
- `SPRINT_PLANNING.md` — per-sprint objective/deliverables/AC/DoD/risks; the working order
- `DECISIONS.md` — ADR log: **append, never rewrite history**; overturns go in a new superseding entry

## Session protocol (ALWAYS)

1. Read `prompt.md` (this), `SPRINT_STATUS.md`, and `git log --oneline -12`. Establish: current sprint,
   last commit, any drift notes.
2. Read the `docs/` needed for the current sprint. Do NOT re-read everything.
3. Execute the current sprint per `SPRINT_PLANNING.md`. Do not start the next sprint before the current
   sprint's Definition of Done is met — unless the user explicitly says otherwise.
4. Enforce global constraints while coding:
   - Four-layer separation (see above). Cross-layer data moves only through the typed JSON artifacts
     (`project/` serialization contract: sorted keys, 4-decimal floats).
   - Determinism: no RNG anywhere; fixed ffmpeg args (`-nostdin`, pinned threads/filter chain); no network
     in runtime paths; deterministic decode (whisper greedy, pinned model sha) with `manifest.json` stamps.
   - No new runtime dependency outside the evaluated stack (DEPENDENCIES.md). Any justified addition goes
     through a DECISIONS.md entry first.
   - `score/` functions stay **pure** (feature vector → float), zero I/O — this is what makes the engine
     testable and portable.
5. Verify: `ruff check` + `ruff format --check` + `pytest` (add/adjust tests alongside code, no test that
   needs network). For media features, assert via ffprobe.
6. Commit major changes following the conventions below; include the SPRINT_STATUS update in that work's
   commit or a dedicated `chore(status): ...` commit.
7. Report back concisely: sprint worked, what changed, DoD status, next action.

## Commit conventions

- One logical change per commit. Prefixes:
  - `sprint<N>(<scope>): <summary>` — e.g. `sprint2(audio): energy windows + silence detection`
  - `docs: ...` — doc-only changes
  - `chore: ...` — tooling / no behavior change
  - `fix: ...` / `test: ...`
- Commit when: a sprint hits its DoD, a module lands, a JSON schema bumps, an ADR is added, docs change
  materially, or SPRINT_STATUS flips a sprint.
- Style: lowercase, imperative, subject ≤ 72 chars, body for rationale when non-obvious. Conventional-commits-shaped, not pedantic.
- Never commit: whisper model binaries (gitignored; sha256 recorded in `manifest.json`), secrets, temp/project dirs.
- `docs/DECISIONS.md` is append-only; never edit an Accepted entry retroactively.

## Definition of Done (a sprint is only Done when)

- All acceptance criteria in `SPRINT_PLANNING.md` for that sprint pass.
- `ruff` + `pytest` green; new logic has tests (score/segment/rank/caption: line-coverage parity).
- Any config/schema/behavior change has: docs updated in the same change, `SPRINT_STATUS.md` updated,
  and a `DECISIONS.md` entry if it overturns a documented decision.
- A done commit exists for it and `git status` is clean.

## Guardrails

- MVP scope (PRD §7–§8) is fixed. If work drifts outside scope or grows ambiguous, **stop and ask the user**
  rather than proceeding on assumptions.
- Any AI/model addition to the pipeline requires a written rationale + evaluation plan in `DECISIONS.md`,
  and must survive fixture evaluation — never adopted for "being smarter".
- Degraded paths (`--no-transcript`, `--no-visual`, missing libass) must never silently change behavior:
  log a warning + stamp `manifest.degraded`.
- If a component cannot be made deterministic, mark it (`deterministic: false`) in manifest and document it —
  do not fake determinism.
- Keep `prompt.md`/`SPRINT_STATUS.md` current so the next session resumes without guessing.

## End-of-session self-check

- SPRINT_STATUS accurate? git log mirrors reality?
- SCORING_ENGINE.md matches the code (SCORING_VERSION stamped where scoring lives)?
- Could a fresh `clipper` cold-start succeed on a 6-min talking-head fixture per PRD §8?