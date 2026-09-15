"""Feature builder: per-candidate inputs extracted from the analysis artifacts.

Every term and penalty rule consumes a small JSON-safe input dict embedded in the
enriched `candidates.json` (`TermScore.inputs`). That embedding is what makes a
re-score a pure function of candidates.json + config (CLI_SPEC.md `clipper score`):
the first score pass reads `analysis.json` to build these inputs; later passes
(tuned weights/caps) read the embedded inputs and re-apply the config only.
Zero I/O here — all inputs come in as validated pydantic models / dicts.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

from scoria.audio.models import AudioInfo
from scoria.config.schema import ScoriaConfig
from scoria.project.jsonio import normalize
from scoria.segment.boundaries import BOUNDARY_DEDUPE_S
from scoria.segment.models import CandidatesInfo
from scoria.transcript.models import TranscriptInfo, Word
from scoria.visual.models import VisualInfo

_HOOK_HEAD_SECONDS = 2.0
_TAIL_SECONDS = 1.0

_ALNUM = re.compile(r"[^0-9a-z]")


def normalize_token(text: str) -> str:
    """Lowercase alnum-only token (SIGNALS.md: normalized text, word-boundary)."""
    return _ALNUM.sub("", text.lower())


@dataclass(frozen=True)
class CandidateFeatures:
    candidate_id: str
    start: float
    end: float
    duration: float
    terms: dict[str, dict[str, Any]] = field(default_factory=dict)
    penalties: dict[str, dict[str, Any]] = field(default_factory=dict)


def _range(slice_: list[int]) -> tuple[int, int]:
    """Expanded index slices are contiguous `range(lo, hi)`; recover the bounds."""
    if not slice_:
        return (0, 0)
    return (slice_[0], slice_[-1] + 1)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _edge_silence(spans: list[tuple[float, float]], start: float, end: float) -> list[list[float]]:
    """Silence spans overlapping the candidate window (absolute seconds)."""
    return [[s, e] for s, e in spans if s < end and e > start]


def _covering_index(starts: list[float], point: float) -> int:
    """Index of the latest start ≤ point, or -1."""
    return bisect_right(starts, point) - 1


def _nearest_gap(points: list[float], point: float) -> float | None:
    if not points:
        return None
    idx = bisect_right(points, point)
    candidates: list[float] = []
    if idx < len(points):
        candidates.append(abs(point - points[idx]))
    if idx > 0:
        candidates.append(abs(point - points[idx - 1]))
    return min(candidates) * 1000.0  # ms


def _boundary_gap_ms(
    point: float,
    times: list[float],
    sentences: list,
    covering_index: int,
    *,
    use_start: bool,
) -> float | None:
    """Gap to the boundary that matters for completeness/penalties.

    Inside a sentence → the distance to *that* sentence's start/end boundary
    (ends of a thought); in silence/gaps between thoughts → nearest such boundary.
    """
    if covering_index >= 0 and sentences[covering_index].end > point:
        boundary = sentences[covering_index].start if use_start else sentences[covering_index].end
        return abs(point - boundary) * 1000.0
    return _nearest_gap(times, point)


def build_candidate_features(
    analysis_data: dict,
    info: CandidatesInfo,
    config: ScoriaConfig,
) -> list[CandidateFeatures]:
    """Translate analysis.json + candidates into per-candidate input payloads.

    The embedding contract (SCORING_ENGINE.md §1): each input dict carries exactly
    what the corresponding term/rule needs to re-run against a different config.
    """

    audio = (
        AudioInfo.model_validate(analysis_data["audio"])
        if analysis_data.get("audio") is not None
        else None
    )
    transcript = (
        TranscriptInfo.model_validate(analysis_data["transcript"])
        if analysis_data.get("transcript") is not None
        else None
    )
    visual = (
        VisualInfo.model_validate(analysis_data["visual"])
        if analysis_data.get("visual") is not None
        else None
    )

    sentences = transcript.sentences if transcript else []
    words: list[Word] = transcript.words if transcript else []
    sentence_starts = [s.start for s in sentences]
    sentence_ends = [s.end for s in sentences]
    scene_times = [sc.time for sc in visual.scenes] if visual else []
    silence_spans = [(sp.start, sp.end) for sp in audio.silence] if audio else []

    rms = audio.rms if audio else []
    energy = audio.energy if audio else []
    rms_p95 = audio.rms_p95 if audio else 0.0
    window_seconds = audio.window_seconds if audio else 0.05
    clip_fraction = audio.peaks.clip_fraction if audio else 0.0

    win_start, win_end = info.window_start, info.window_end

    def windowed_base() -> float:
        if not words:
            return 0.0
        base_speech = sum(
            min(w.end, win_end) - max(w.start, win_start)
            for w in words
            if w.start < win_end and w.end > win_start
        )
        if base_speech <= 0.0:
            return 0.0
        return len(words) / (base_speech / 60.0)

    wpm_base = windowed_base()

    def audio_bounds(start: float, end: float) -> tuple[int, int]:
        i0 = max(0, math.floor(start / window_seconds))
        i1 = min(len(rms), math.ceil(end / window_seconds))
        return i0, i1

    out: list[CandidateFeatures] = []
    for candidate in info.candidates:
        start, end = candidate.start, candidate.end
        duration = max(end - start, 1e-9)

        s_lo, s_hi = _range(candidate.slices.sentences)
        w_lo, w_hi = _range(candidate.slices.words)
        sc_lo, sc_hi = _range(candidate.slices.scenes)
        i0, i1 = audio_bounds(start, end)

        cand_words = words[w_lo:w_hi]
        window_tokens: list[str] = []
        word_fractions: list[float] = []
        for word in cand_words:
            token = normalize_token(word.text)
            if not token:
                continue
            window_tokens.append(token)
            word_fractions.append((word.start - start) / duration)

        # -- audio energy / continuity terms ----------------------------------
        e_ratio = 0.0
        if rms and rms_p95 > 0.0 and i1 > i0:
            e_ratio = _mean([min(r / rms_p95, 1.0) for r in rms[i0:i1]])

        # hook-burst math uses the energy (power) series — AudioInfo docstring.
        clip_energy = _mean(energy[i0:i1])
        head_idx = min(i1, i0 + math.ceil(_HOOK_HEAD_SECONDS / window_seconds))
        head_energy = _mean(energy[i0:head_idx])
        burst_ratio = head_energy / clip_energy if clip_energy > 0.0 else 0.0

        clip_rms = _mean(rms[i0:i1])
        tail_idx = max(i0, math.floor((end - _TAIL_SECONDS) / window_seconds))
        tail_rms = _mean(rms[tail_idx:i1])

        # -- speech / completeness --------------------------------------------
        speech_time = sum(min(word.end, end) - word.start for word in cand_words)
        wpm = (len(window_tokens) / (speech_time / 60.0)) if speech_time > 0.0 else 0.0

        first_sentence = None
        covering_start = _covering_index(sentence_starts, start)
        if covering_start >= 0 and sentences[covering_start].end > start:
            first_sentence = sentences[covering_start]
        elif s_lo < s_hi:
            first_sentence = sentences[s_lo]

        covering_end = _covering_index(sentence_ends, end)
        gap_start_ms = _boundary_gap_ms(
            start, sentence_starts, sentences, covering_start, use_start=True
        )
        gap_end_ms = _boundary_gap_ms(end, sentence_ends, sentences, covering_end, use_start=False)

        def on_point(point: float, times: list[float]) -> bool:
            return any(abs(t - point) <= BOUNDARY_DEDUPE_S for t in times)

        def on_silence_or_scene(point: float) -> bool:
            if any(abs(t - point) <= BOUNDARY_DEDUPE_S for t in scene_times):
                return True
            return any(
                abs(s - point) <= BOUNDARY_DEDUPE_S or abs(e - point) <= BOUNDARY_DEDUPE_S
                for s, e in silence_spans
            )

        start_on_sentence = on_point(start, sentence_starts)
        end_on_sentence = on_point(end, sentence_ends)
        start_on_other = on_silence_or_scene(start)
        end_on_other = on_silence_or_scene(end)

        inside_sentence = covering_start >= 0 and sentences[covering_start].end > start

        word_starts = [w.start for w in words]
        w_idx = _covering_index(word_starts, end)
        # A candidate *landing inside* a word span: strictly after the word's
        # start AND before its end. An end exactly on a word start/end boundary
        # is a clean cut, not a mid-word end.
        ends_inside_word = w_idx >= 0 and words[w_idx].start < end < words[w_idx].end

        mean_wps = (
            _mean([len(sentences[i].words) for i in range(s_lo, s_hi)]) if s_hi > s_lo else 0.0
        )

        repeat_count = sum(
            1 for i in range(1, len(window_tokens)) if window_tokens[i] == window_tokens[i - 1]
        )

        scene_density = (sc_hi - sc_lo) / (duration / 60.0)

        # Normalize every input to the serialization contract (4-decimal floats)
        # before scoring, so the embedded inputs are exactly the values that were
        # scored — a config-only re-score from those inputs is byte-identical to
        # the first pass (Sprint 5 acceptance: two runs identical).
        feat = CandidateFeatures(
            candidate_id=candidate.id,
            start=start,
            end=end,
            duration=duration,
            terms={
                name: normalize(payload)
                for name, payload in {
                    "audio_energy": {"energy_ratio": e_ratio},
                    "speech_density": {
                        "speech_time_s": speech_time,
                        "window_duration_s": duration,
                    },
                    "pacing": {"wpm": wpm, "wpm_base": wpm_base},
                    "hook": {
                        "first_sentence_text": first_sentence.text if first_sentence else "",
                        "first_sentence_words": (
                            len(first_sentence.words) if first_sentence else 0
                        ),
                        "window_words": window_tokens,
                        "word_start_fractions": word_fractions,
                        "energy_burst_ratio": burst_ratio,
                    },
                    "completeness": {
                        "gap_start_ms": gap_start_ms,
                        "gap_end_ms": gap_end_ms,
                        "start_on_sentence": start_on_sentence,
                        "end_on_sentence": end_on_sentence,
                        "start_on_scene_or_silence": start_on_other,
                        "end_on_scene_or_silence": end_on_other,
                    },
                    "visual_activity": {"scene_density": scene_density},
                    "keyword_density": {
                        "window_words": window_tokens,
                        "window_duration_s": duration,
                    },
                    "sentence_quality": {"mean_wps": mean_wps},
                }.items()
            },
            penalties={
                name: normalize(payload)
                for name, payload in {
                    "leading_silence": {
                        "edge_silence": _edge_silence(silence_spans, start, end),
                        "candidate_start": start,
                    },
                    "trailing_silence": {
                        "edge_silence": _edge_silence(silence_spans, start, end),
                        "candidate_end": end,
                    },
                    "dead_air": {
                        "edge_silence": _edge_silence(silence_spans, start, end),
                        "candidate_start": start,
                        "candidate_end": end,
                    },
                    "mid_sentence_start": {
                        "gap_start_ms": gap_start_ms,
                        "inside_sentence": inside_sentence,
                        "start_on_sentence": start_on_sentence,
                    },
                    "mid_word_end": {"ends_inside_word": ends_inside_word},
                    "low_energy_tail": {
                        "tail_mean_rms": tail_rms,
                        "clip_mean_rms": clip_rms,
                    },
                    "flub_repeats": {
                        "repeat_count": repeat_count,
                        "word_count": len(window_tokens),
                    },
                    "peak_clipping": {"clip_fraction": clip_fraction},
                }.items()
            },
        )
        out.append(feat)
    return out
