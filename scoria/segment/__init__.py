"""Segmentation: boundary list + raw candidate windows (`candidates.json`)."""

from scoria.segment.boundaries import BOUNDARY_DEDUPE_S, build_boundaries
from scoria.segment.generator import WindowSpec, generate_candidates
from scoria.segment.models import (
    BOUNDARY_SOURCE_ORDER,
    CANDIDATES_SCHEMA,
    CANDIDATES_VERSION,
    Boundary,
    Candidate,
    CandidatesInfo,
    CandidateSlices,
)
from scoria.segment.pipeline import build_candidates

__all__ = [
    "BOUNDARY_DEDUPE_S",
    "BOUNDARY_SOURCE_ORDER",
    "CANDIDATES_SCHEMA",
    "CANDIDATES_VERSION",
    "Boundary",
    "Candidate",
    "CandidateSlices",
    "CandidatesInfo",
    "WindowSpec",
    "build_boundaries",
    "build_candidates",
    "generate_candidates",
]
