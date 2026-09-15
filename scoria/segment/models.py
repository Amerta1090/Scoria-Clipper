"""Typed segmentation output: the raw candidates document (`candidates.json`).

Sprint 4 scope is the boundary list + candidate windows (ARCHITECTURE.md §5.4
window generator). Each candidate is a raw window into the media with alignment
metadata — scores are added by Sprint 5; rankings by Sprint 6. All times are
absolute analysis-window seconds; floats are rounded by the serialization
contract on write.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CANDIDATES_SCHEMA = "candidates"
CANDIDATES_VERSION = 1

# Canonical source label ordering for `aligned_to` / `boundaries[].sources`.
BOUNDARY_SOURCE_ORDER = ("sentence_start", "sentence_end", "silence_start", "silence_end", "scene")


class Boundary(BaseModel):
    time: float
    sources: list[str]


class CandidateSlices(BaseModel):
    audio: list[int]
    sentences: list[int]
    words: list[int]
    scenes: list[int]


class Candidate(BaseModel):
    id: str
    start: float
    end: float
    duration: float
    aligned_to: list[str]
    mid_sentence_start: bool
    mid_sentence_end: bool
    hard_cut: bool
    slices: CandidateSlices


class SegmentConfigSnapshot(BaseModel):
    min_duration: float
    pref_min: float
    pref_max: float
    max_duration: float
    max_candidates_per_start: int
    hard_cut_margin: float
    scene_detection_threshold: float


class CandidatesInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_schema: Literal["candidates"] = Field(CANDIDATES_SCHEMA, alias="schema")
    version: int
    media_duration: float
    window_start: float
    window_end: float
    config: SegmentConfigSnapshot
    boundaries: list[Boundary]
    candidates: list[Candidate]
