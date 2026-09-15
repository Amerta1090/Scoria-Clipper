"""Pure sub-score functions (SCORING_ENGINE.md §2.1–2.9).

Each term is a deterministic `(inputs, config) → (raw, normalized, note)` —
no state, no I/O. `inputs` is the embedded payload built by `features`; `config`
supplies the band/bounds values so a re-score against a tuned config stays a pure
function of candidates.json + config. `raw` differs from `normalized` only for
terms that define a pre-clamp value (hook); every other term returns raw ==
normalized because they are already clamped by their curve.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scoria.config.schema import ScoriaConfig
from scoria.score.features import normalize_token
from scoria.score.math import smoothstep, trapezoid

# Pacing bell knots (SCORING_ENGINE §2.3): linear up 0→1 between lo–1.0, 1 at
# 1.0–1.2, linear down to 0 at 1.5. `pacing_band.hi` and `wpm_base_window` stay
# reserved (documented in SCORING_ENGINE) — the soft/hard numerals are the spec.
PACE_PEAK_START = 1.0
PACE_PEAK_END = 1.2
PACE_TAIL_END = 1.5

# Completeness tolerances (SCORING_ENGINE §2.5): exact boundary match (±50 ms is
# the boundary dedupe window), mid-grade within 300 ms, linear decay to 0 at 2 s.
COMPLETENESS_START_TOL_MS = 50
COMPLETENESS_MID_TOL_MS = 300
COMPLETENESS_DECAY_MS = 2000

# Missing-gap sentinel: no sentence boundaries in the video at all.
NO_BOUNDARY = object()

TermOutput = tuple[float | None, float, str]


def _phrase_occurrences(window_tokens: list[str], phrase_tokens: list[str]) -> int:
    """Occurrence count of a phrase in normalized window tokens.

    Single-token phrases match by membership (frequency); multi-word phrases
    match adjacent token runs (non-overlapping).
    """
    if not phrase_tokens or not window_tokens:
        return 0
    if len(phrase_tokens) == 1:
        return window_tokens.count(phrase_tokens[0])
    count = 0
    i = 0
    n = len(phrase_tokens)
    while i <= len(window_tokens) - n:
        if window_tokens[i : i + n] == phrase_tokens:
            count += 1
            i += n
        else:
            i += 1
    return count


def _first_occurrence(window_tokens: list[str], phrase_tokens: list[str]) -> int:
    if not phrase_tokens or not window_tokens:
        return -1
    n = len(phrase_tokens)
    for i in range(len(window_tokens) - n + 1):
        if window_tokens[i : i + n] == phrase_tokens:
            return i
    return -1


def _g_score(
    gap_ms: float | None,
    on_sentence: bool,
    on_scene_or_silence: bool,
) -> float:
    """The §2.5 boundary-grade branch: 1 exact, 0.5 mid-grade, decay otherwise."""
    if gap_ms is None:
        return 0.0
    if on_sentence:
        return 1.0
    if on_scene_or_silence and gap_ms <= COMPLETENESS_MID_TOL_MS:
        return 0.5
    return max(0.0, 1.0 - gap_ms / COMPLETENESS_DECAY_MS)


def term_audio_energy(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    band = config.scoring.terms.energy_bounds
    e = float(inputs.get("energy_ratio", 0.0))
    s = smoothstep(e, band.low, band.high)
    return s, s, f"E {e:.2f} of R95"


def term_speech_density(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    band = config.scoring.terms.speech_bounds
    speech = float(inputs.get("speech_time_s", 0.0))
    window = float(inputs.get("window_duration_s", 1.0))
    d = speech / window if window > 0.0 else 0.0
    s = smoothstep(d, band.low, band.high)
    return s, s, f"{d * 100:.0f}% speech"


def term_pacing(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    band = config.scoring.terms.pacing_band
    wpm = float(inputs.get("wpm", 0.0))
    base = float(inputs.get("wpm_base", 0.0))
    r = wpm / base if base > 0.0 else 0.0
    s = trapezoid(r, band.lo, PACE_PEAK_START, PACE_PEAK_END, PACE_TAIL_END)
    return s, s, f"wpm {wpm:.0f} vs base {base:.0f}"


def term_hook(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    terms = config.scoring.terms
    phrases = config.transcript.hooks.phrases
    window_words = list(inputs.get("window_words", []))
    fractions = list(inputs.get("word_start_fractions", []))

    hook_phrase = 0.0
    for phrase in phrases:
        tokens = [normalize_token(word) for word in phrase.split()]
        tokens = [t for t in tokens if t]
        idx = _first_occurrence(window_words, tokens)
        if idx < 0:
            continue
        fraction = fractions[idx] if idx < len(fractions) else 1.0
        if fraction <= terms.hook_first_fraction:
            hook_phrase = max(
                hook_phrase,
                1.0 - 0.5 * (fraction / terms.hook_first_fraction),
            )
        else:
            hook_phrase = max(hook_phrase, 0.5)

    text = str(inputs.get("first_sentence_text", ""))
    first_len = int(inputs.get("first_sentence_words", 0))
    open_question = (
        1.0
        if text.strip().endswith("?") and first_len <= terms.hook_max_first_sentence_words
        else 0.0
    )
    open_short = 1.0 if 0 < first_len <= terms.hook_short_first_sentence_words else 0.0

    ratio = float(inputs.get("energy_burst_ratio", 0.0))
    open_burst = terms.hook_burst_value * min(1.0, ratio / terms.hook_burst_multiplier)

    raw = max(hook_phrase, open_question, open_short, open_burst)
    normalized = max(0.0, min(1.0, raw))
    return raw, normalized, _hook_note(raw, open_question, open_short, first_len)


def _hook_note(raw: float, open_question: float, open_short: float, first_len: int) -> str:
    if open_question:
        return f"question opener ({first_len} words)"
    if open_short:
        return f"short opener ({first_len} words)"
    return f"raw {raw:.2f}"


def term_completeness(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    gap_s = inputs.get("gap_start_ms")
    gap_e = inputs.get("gap_end_ms")
    g_start = _g_score(
        gap_s,
        bool(inputs.get("start_on_sentence", False)),
        bool(inputs.get("start_on_scene_or_silence", False)),
    )
    g_end = _g_score(
        gap_e,
        bool(inputs.get("end_on_sentence", False)),
        bool(inputs.get("end_on_scene_or_silence", False)),
    )
    s = 0.5 * g_start + 0.5 * g_end
    note = f"g_start {g_start:.2f} (gap {gap_s}ms), g_end {g_end:.2f} (gap {gap_e}ms)"
    return s, s, note


def term_visual_activity(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    # ADR-015: motion-intensity pass lands in a later sprint; weight stays active
    # when the visual signal exists but the term is a no-op until then.
    return None, 0.0, "no-op until motion pass (ADR-015)"


def term_keyword_density(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    band = config.scoring.terms.keyword_band
    keywords = config.transcript.keywords.terms
    window_words = list(inputs.get("window_words", []))
    window = float(inputs.get("window_duration_s", 1.0))

    hits = 0
    for keyword in keywords:
        tokens = [normalize_token(word) for word in keyword.split()]
        tokens = [t for t in tokens if t]
        hits += _phrase_occurrences(window_words, tokens)
    hpm = hits / (window / 60.0) if window > 0.0 else 0.0
    s = smoothstep(hpm, band.low, band.high)
    return s, s, f"{hpm:.1f} hits/min ({hits} hits)"


def term_sentence_quality(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    band = config.scoring.terms.sentence_band
    wps = float(inputs.get("mean_wps", 0.0))
    s = trapezoid(wps, band.wlo, band.lo, band.hi, band.whi)
    return s, s, f"mean {wps:.1f} wps"


def term_face_presence(inputs: dict[str, Any], config: ScoriaConfig) -> TermOutput:
    # SCORING_ENGINE §2.9: interface ready, signal later — never scored today.
    return None, 0.0, "no face signal — post-MVP (SCORING_ENGINE §2.9)"


TERM_FUNCS: dict[str, Callable[[dict[str, Any], ScoriaConfig], TermOutput]] = {
    "audio_energy": term_audio_energy,
    "speech_density": term_speech_density,
    "pacing": term_pacing,
    "hook": term_hook,
    "completeness": term_completeness,
    "visual_activity": term_visual_activity,
    "keyword_density": term_keyword_density,
    "sentence_quality": term_sentence_quality,
    "face_presence": term_face_presence,
}
