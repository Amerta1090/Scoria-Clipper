"""Segmentation pipeline: analysis.json + config → candidates document.

`build_candidates` is the Sprint 4 core: it validates the analysis sections into
their typed models, derives the boundary list from the available signals
(silence ∪ sentences ∪ scenes — segments degrade gracefully to silence∪scene
when the transcript is absent, per docs/DECISIONS.md OQ2), runs the window
generator, and decorates every window with alignment metadata and feature
slices covering the audio window range and the contained sentences/words/scenes.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right

from scoria.audio.models import AudioInfo
from scoria.config.schema import ScoriaConfig
from scoria.ingest.models import MediaInfo
from scoria.segment.boundaries import build_boundaries
from scoria.segment.generator import WindowSpec, generate_candidates
from scoria.segment.models import (
    CANDIDATES_VERSION,
    Candidate,
    CandidatesInfo,
    CandidateSlices,
    SegmentConfigSnapshot,
)
from scoria.transcript.models import TranscriptInfo
from scoria.visual.models import VisualInfo


def _aligned(spec: WindowSpec) -> list[str]:
    return list(dict.fromkeys([*spec.start_sources, *spec.end_sources]))


def _has_sentence(sources: tuple[str, ...]) -> bool:
    return any(source.startswith("sentence") for source in sources)


def _index_slice(times: list[float], start: float, end: float, *, include_end: bool) -> list[int]:
    lo = bisect_left(times, start)
    hi = bisect_right(times, end) if include_end else bisect_left(times, end)
    return list(range(lo, hi))


def _audio_slice(windows: int, window_seconds: float, start: float, end: float) -> list[int]:
    """Compact audio slice: [first, last+1) window indices covered by [start, end)."""
    if windows <= 0:
        return []
    i0 = max(0, math.floor(start / window_seconds))
    i1 = min(windows, math.ceil(end / window_seconds))
    return [i0, i1]


def _build_candidates(
    spec: WindowSpec,
    *,
    index: int,
    sentence_times: list[float],
    word_times: list[float],
    scene_times: list[float],
    windows: int,
    window_seconds: float,
) -> Candidate:
    return Candidate(
        id=f"c{index:04d}",
        start=spec.start,
        end=spec.end,
        duration=spec.end - spec.start,
        aligned_to=_aligned(spec),
        mid_sentence_start=not _has_sentence(spec.start_sources),
        mid_sentence_end=not _has_sentence(spec.end_sources),
        hard_cut=spec.hard_cut,
        slices=CandidateSlices(
            audio=_audio_slice(windows, window_seconds, spec.start, spec.end),
            sentences=_index_slice(sentence_times, spec.start, spec.end, include_end=False),
            words=_index_slice(word_times, spec.start, spec.end, include_end=False),
            scenes=_index_slice(scene_times, spec.start, spec.end, include_end=True),
        ),
    )


def build_candidates(analysis_data: dict, config: ScoriaConfig) -> dict:
    media = MediaInfo.model_validate(analysis_data["media"])
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
    silence = audio.silence if audio else []
    scenes = visual.scenes if visual else []

    boundaries = build_boundaries(
        silence=[(span.start, span.end) for span in silence],
        sentences=[(sentence.start, sentence.end) for sentence in sentences],
        scenes=[(scene.time, scene.time) for scene in scenes],
    )

    window = media.analysis
    segment = config.segment
    windows = generate_candidates(
        boundaries,
        media_start=window.start,
        media_end=window.end,
        min_duration=segment.min_duration,
        pref_min=segment.preferred.min,
        pref_max=segment.preferred.max,
        max_duration=segment.max_duration,
        max_candidates_per_start=segment.max_candidates_per_start,
        hard_cut_margin=segment.hard_cut_margin,
    )

    sentence_times = [sentence.start for sentence in sentences]
    word_times = [word.start for word in sentences for word in word.words]
    scene_times = [scene.time for scene in scenes]
    audio_windows = audio.windows if audio else 0
    window_seconds = audio.window_seconds if audio else 1.0

    candidates = [
        _build_candidates(
            spec,
            index=index,
            sentence_times=sentence_times,
            word_times=word_times,
            scene_times=scene_times,
            windows=audio_windows,
            window_seconds=window_seconds,
        )
        for index, spec in enumerate(windows, start=1)
    ]

    info = CandidatesInfo(
        schema="candidates",
        version=CANDIDATES_VERSION,
        media_duration=media.duration,
        window_start=window.start,
        window_end=window.end,
        config=SegmentConfigSnapshot(
            min_duration=segment.min_duration,
            pref_min=segment.preferred.min,
            pref_max=segment.preferred.max,
            max_duration=segment.max_duration,
            max_candidates_per_start=segment.max_candidates_per_start,
            hard_cut_margin=segment.hard_cut_margin,
            scene_detection_threshold=segment.scene_detection_threshold,
        ),
        boundaries=boundaries,
        candidates=candidates,
    )
    return info.model_dump(mode="json", by_alias=True)
