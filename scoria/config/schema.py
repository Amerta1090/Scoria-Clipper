"""Pydantic models for the full CONFIGURATION.md v1 schema.

Defaults here are the single source of truth for the default config (`clipper config
write-defaults` dumps this model). Unknown keys are rejected (`extra="forbid"`) so a typo
is an error (exit 2), never a silent ignore. Cross-field rules in CONFIGURATION.md §3 are
enforced by `model_validator`s.

Weights: raw weights may sum to < 1 (the default set sums to 0.89 — a disabled term's
weight is 0). At scoring time the enabled weights are renormalized so their sum is 1.0
(SCORING_ENGINE.md §5). `enabled_weights()`/`renormalized_weights()` expose that view.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scoria.errors import ConfigError

_SUPPORTED_CONFIG_VERSION = 1

# Terms disabled when the transcript signal is unavailable (SCORING_ENGINE.md §5).
# `completeness` grades sentence-boundary alignment — with no transcript there are
# no sentence boundaries, so it degrades to the silent-transcript path too.
TRANSCRIPT_DISABLED_TERMS: frozenset[str] = frozenset(
    {
        "speech_density",
        "pacing",
        "hook",
        "completeness",
        "keyword_density",
        "sentence_quality",
    }
)
# Terms whose weight is 0 (disabled by default).
ZERO_WEIGHT_TERMS: frozenset[str] = frozenset({"face_presence"})

_WEIGHT_FIELDS: Iterable[str] = (
    "audio_energy",
    "speech_density",
    "pacing",
    "hook",
    "completeness",
    "visual_activity",
    "keyword_density",
    "sentence_quality",
    "face_presence",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictModel):
    dir: str = "auto"
    overwrite: bool = False
    keep_temp: bool = False
    temp_dir: str = "auto"


class FrameConfig(StrictModel):
    fps: int = Field(default=4, ge=1)
    width: int = Field(default=64, ge=2)
    height: int = Field(default=36, ge=2)
    pix_fmt: str = "gray"


class MediaConfig(StrictModel):
    min_duration: float = Field(default=8.0, ge=0.0)
    max_duration: float = Field(default=7200.0, ge=0.0)
    analyze_audio_rate: int = Field(default=16000, ge=1)
    frame: FrameConfig = Field(default_factory=FrameConfig)

    @model_validator(mode="after")
    def _check_max_gte_min(self) -> MediaConfig:
        if self.max_duration <= self.min_duration:
            raise ConfigError(
                f"media.max_duration ({self.max_duration}) must exceed media.min_duration "
                f"({self.min_duration})"
            )
        return self


class InputConfig(StrictModel):
    video_stream: str | int = "auto"


class SentenceConfig(StrictModel):
    max_gap_seconds: float = Field(default=1.2, ge=0.0)
    min_sentence_words: int = Field(default=2, ge=1)
    force_punctuation: bool = True


class HooksConfig(StrictModel):
    phrases: list[str] = Field(
        default_factory=lambda: [
            "yang perlu kamu tahu",
            "jangan lupa subscribe",
            "kunci",
            "rahasia",
            "tips",
            "cara",
            "ternyata",
        ]
    )


class KeywordsConfig(StrictModel):
    terms: list[str] = Field(
        default_factory=lambda: ["kunci", "tips", "cara", "tutorial", "review", "harga"]
    )


class VisualConfig(StrictModel):
    enabled: bool = True


class TranscriptConfig(StrictModel):
    enabled: bool = True
    engine: Literal["whisper.cpp", "off"] = "whisper.cpp"
    binary: str = "whisper-cli"
    model: str = "model/ggml-small.bin"
    model_sha256: str = ""
    language: str = "auto"
    greedy: bool = True
    threads: int = Field(default=4, ge=1)
    segment_from_whisper: bool = True
    sentence: SentenceConfig = Field(default_factory=SentenceConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    keywords: KeywordsConfig = Field(default_factory=KeywordsConfig)


class SilenceConfig(StrictModel):
    threshold_db: float = Field(default=-35.0)
    min_duration: float = Field(default=0.35, ge=0.0)
    edge_tolerance: float = Field(default=0.4, ge=0.0)
    dead_air: float = Field(default=1.5, ge=0.0)


class AudioConfig(StrictModel):
    window_ms: int = Field(default=50, ge=1)
    analyze_start: float = Field(default=0.0, ge=0.0)
    analyze_end: float = Field(default=0.0, ge=0.0)
    peak_threshold: float = Field(default=0.999, ge=0.0, le=1.0)
    silence: SilenceConfig = Field(default_factory=SilenceConfig)

    @model_validator(mode="after")
    def _check_window_ordering(self) -> AudioConfig:
        if self.analyze_end > 0.0 and self.analyze_end <= self.analyze_start:
            raise ConfigError(
                "audio.analyze_end must be 0 (analyse whole file) or greater than "
                f"audio.analyze_start ({self.analyze_start})"
            )
        return self


class PreferredConfig(StrictModel):
    min: float = Field(default=35.0, ge=0.0)
    max: float = Field(default=45.0, ge=0.0)


class SegmentConfig(StrictModel):
    min_duration: float = Field(default=20.0, ge=0.0)
    max_duration: float = Field(default=60.0, ge=0.0)
    preferred: PreferredConfig = Field(default_factory=PreferredConfig)
    scene_detection_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    max_candidates_per_start: int = Field(default=2, ge=1)
    hard_cut_margin: float = Field(default=0.25, ge=0.0)

    @model_validator(mode="after")
    def _check_duration_ordering(self) -> SegmentConfig:
        if not (self.min_duration <= self.preferred.min <= self.preferred.max <= self.max_duration):
            raise ConfigError(
                "segment.min_duration ≤ segment.preferred.min ≤ segment.preferred.max ≤ "
                f"segment.max_duration required, got {self.min_duration} ≤ {self.preferred.min} "
                f"≤ {self.preferred.max} ≤ {self.max_duration}"
            )
        return self


class WeightsConfig(StrictModel):
    audio_energy: float = Field(default=0.09, ge=0.0)
    speech_density: float = Field(default=0.13, ge=0.0)
    pacing: float = Field(default=0.10, ge=0.0)
    hook: float = Field(default=0.15, ge=0.0)
    completeness: float = Field(default=0.20, ge=0.0)
    visual_activity: float = Field(default=0.10, ge=0.0)
    keyword_density: float = Field(default=0.06, ge=0.0)
    sentence_quality: float = Field(default=0.06, ge=0.0)
    face_presence: float = Field(default=0.00, ge=0.0)

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in _WEIGHT_FIELDS}


class BoundsConfig(StrictModel):
    low: float = Field(default=0.15, ge=0.0)
    high: float = Field(default=0.75, ge=0.0)


class BandConfig(StrictModel):
    lo: float = Field(default=0.85, ge=0.0)
    hi: float = Field(default=1.35, ge=0.0)


class SoftHardConfig(StrictModel):
    soft: float = Field(default=1.5, ge=0.0)
    hard: float = Field(default=6.0, ge=0.0)


class WPSBandConfig(StrictModel):
    wlo: float = Field(default=6.0, ge=0.0)
    lo: float = Field(default=9.0, ge=0.0)
    hi: float = Field(default=18.0, ge=0.0)
    whi: float = Field(default=22.0, ge=0.0)


class TermsConfig(StrictModel):
    energy_bounds: BoundsConfig = Field(default_factory=BoundsConfig)
    speech_bounds: BoundsConfig = Field(default_factory=lambda: BoundsConfig(low=0.30, high=0.85))
    pacing_band: BandConfig = Field(default_factory=BandConfig)
    wpm_base_window: float = Field(default=30.0, ge=0.0)
    visual_band: SoftHardConfig = Field(default_factory=SoftHardConfig)
    keyword_band: BoundsConfig = Field(default_factory=lambda: BoundsConfig(low=0.5, high=3.0))
    sentence_band: WPSBandConfig = Field(default_factory=WPSBandConfig)
    hook_first_fraction: float = Field(default=0.30, ge=0.0, le=1.0)
    hook_max_first_sentence_words: int = Field(default=12, ge=1)
    hook_short_first_sentence_words: int = Field(default=8, ge=1)
    hook_burst_multiplier: float = Field(default=3.0, ge=1.0)
    hook_burst_value: float = Field(default=0.8, ge=0.0, le=1.0)


class PenaltyFlagsConfig(StrictModel):
    leading_silence: bool = True
    trailing_silence: bool = True
    dead_air: bool = True
    mid_sentence_start: bool = True
    mid_word_end: bool = True
    low_energy_tail: bool = True
    flub_repeats: bool = True
    peak_clipping: bool = False


class PenaltyCapsConfig(StrictModel):
    edge_silence: float = Field(default=0.10, ge=0.0)
    dead_air: float = Field(default=0.15, ge=0.0)
    mid_sentence: float = Field(default=0.15, ge=0.0)
    mid_word: float = Field(default=0.20, ge=0.0)
    tail: float = Field(default=0.05, ge=0.0)
    flub: float = Field(default=0.05, ge=0.0)
    clip: float = Field(default=0.02, ge=0.0)


class PenaltiesConfig(StrictModel):
    config: PenaltyFlagsConfig = Field(default_factory=PenaltyFlagsConfig)
    caps: PenaltyCapsConfig = Field(default_factory=PenaltyCapsConfig)
    total_cap: float = Field(default=0.35, ge=0.0)

    @model_validator(mode="after")
    def _check_total_cap(self) -> PenaltiesConfig:
        total = sum(self.caps.model_dump().values())
        if self.total_cap > total:
            raise ConfigError(
                "scoring.penalties.total_cap must not exceed the sum of the per-rule caps "
                f"({total}), got {self.total_cap}"
            )
        return self


class RankingConfig(StrictModel):
    enabled: bool = True
    min_margin: float = Field(default=20.0, ge=0.0)
    lam_overlap: float = Field(default=1.0, ge=0.0)
    lam_similarity: float = Field(default=0.25, ge=0.0)
    lam_gap: float = Field(default=0.15, ge=0.0)
    preferred_gap_factor: float = Field(default=2.0, ge=0.0)
    hard_min_start_gap: float = Field(default=0.0, ge=0.0)


class ScoringConfig(StrictModel):
    version: str = "1.0.0"
    renormalize_disabled: bool = True
    weights: WeightsConfig = Field(default_factory=WeightsConfig)
    terms: TermsConfig = Field(default_factory=TermsConfig)
    penalties: PenaltiesConfig = Field(default_factory=PenaltiesConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)

    def enabled_weights(self) -> dict[str, float]:
        return {name: w for name, w in self.weights.as_dict().items() if w > 0.0}

    def renormalized_weights(
        self, disabled: Iterable[str] = (), transcript_enabled: bool | None = None
    ) -> dict[str, float]:
        if transcript_enabled is False:
            disabled = set(disabled) | TRANSCRIPT_DISABLED_TERMS
        enabled = self.enabled_weights()
        for name in disabled:
            enabled.pop(name, None)
        total = sum(enabled.values())
        if total <= 0.0:
            raise ConfigError(
                "no enabled scoring weights after disabling terms — cannot renormalize"
            )
        return {name: w / total for name, w in enabled.items()}

    @model_validator(mode="after")
    def _check_weights(self) -> ScoringConfig:
        total = sum(self.enabled_weights().values())
        if total <= 0.0:
            raise ConfigError("scoring.weights must contain at least one weight > 0")
        renorm_sum = sum(v / total for v in self.enabled_weights().values())
        if not (0.99 <= renorm_sum <= 1.01):
            raise ConfigError(
                "scoring.weights: renormalized enabled sum must be in [0.99, 1.01], got "
                f"{renorm_sum:.4f}"
            )
        return self


class AssStyleConfig(StrictModel):
    name: str = "Caption"
    font: str = "DejaVu Sans"
    font_size: int = Field(default=58, ge=1)
    primary_colour: str = "&H00FFFFFF"
    outline_colour: str = "&H00000000"
    outline: int = Field(default=3, ge=0)
    shadow: int = Field(default=1, ge=0)
    margin_v: int = Field(default=160, ge=0)
    karaoke_words: bool = True


class CaptionsConfig(StrictModel):
    enabled: bool = True
    format: list[Literal["srt", "ass"]] = Field(default_factory=lambda: ["srt", "ass"])
    burn_in: bool = True
    chars_per_line: int = Field(default=42, ge=1)
    max_lines: int = Field(default=2, ge=1)
    max_duration: float = Field(default=5.1, ge=0.1)
    min_word_count: int = Field(default=1, ge=1)
    prefer_sentence_breaks: bool = True
    wpm: int = Field(default=200, ge=1)
    ass_style: AssStyleConfig = Field(default_factory=AssStyleConfig)
    safe_area_bottom: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_readability(self) -> CaptionsConfig:
        # ADR-018: a (full) caption must stay on screen long enough to be read.
        # 5 chars ≈ 1 word; reading speed `wpm` → minimum on-screen seconds.
        minimum = (self.chars_per_line * self.max_lines / 5.0) / (self.wpm / 60.0)
        if self.max_duration < minimum:
            raise ConfigError(
                f"captions.max_duration {self.max_duration} is below the readability "
                f"minimum {minimum:.2f}s = (chars_per_line·max_lines/5)/(wpm/60); "
                "increase max_duration or lower chars_per_line/max_lines/wpm (ADR-018)"
            )
        return self


class FocusConfig(StrictModel):
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.5, ge=0.0, le=1.0)


class SmoothConfig(StrictModel):
    ema_alpha: float = Field(default=0.10, ge=0.0, le=1.0)
    window_s: float = Field(default=0.5, ge=0.0)


class OutputConfig(StrictModel):
    width: int = Field(default=1080, ge=2)
    height: int = Field(default=1920, ge=2)


class RegionConfig(StrictModel):
    """Normalized source rect feeding the facecam PiP zone (mode: gamer, v1)."""

    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.78, ge=0.0, le=1.0)
    w: float = Field(default=0.35, gt=0.0, le=1.0)
    h: float = Field(default=0.20, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_inside_unit_square(self) -> RegionConfig:
        if self.x + self.w > 1.0 + 1e-9 or self.y + self.h > 1.0 + 1e-9:
            raise ConfigError(
                "reframe.gamer.facecam.region must fit inside [0,1]² "
                f"(x+w ≤ 1 and y+h ≤ 1), got {self.model_dump()}"
            )
        return self


class GameplayZoneConfig(StrictModel):
    """Top zone of the two-zone stack: canvas-height share + x-anchor (mode: gamer, v1)."""

    v_fraction: float = Field(default=0.60, gt=0.0, lt=1.0)
    anchor: Literal["center"] = "center"  # v1: center-anchored crop only


class FacecamZoneConfig(StrictModel):
    """Bottom zone of the two-zone stack: normalized source PiP box (mode: gamer, v1)."""

    region: RegionConfig = Field(default_factory=RegionConfig)


class GamerConfig(StrictModel):
    """Two-zone vertical stack layout (CONFIGURATION.md §1 `reframe.gamer`, Sprint 12).

    Gameplay zone on top (v_fraction of the canvas height, center-anchored cover-fit
    crop → scale), facecam PiP zone on the bottom (the normalized source region,
    cover-fitted inside it). Zones are even-dim, never overlap, and tile the output
    canvas exactly.
    """

    gameplay: GameplayZoneConfig = Field(default_factory=GameplayZoneConfig)
    facecam: FacecamZoneConfig = Field(default_factory=FacecamZoneConfig)


class ReframeConfig(StrictModel):
    mode: Literal["center", "gamer", "faces", "target"] = "center"
    focus: FocusConfig = Field(default_factory=FocusConfig)
    blurbad_threshold: float = Field(default=1.78, ge=0.0)
    output: OutputConfig = Field(default_factory=OutputConfig)
    gamer: GamerConfig = Field(default_factory=GamerConfig)
    smooth: SmoothConfig = Field(default_factory=SmoothConfig)
    even_dim: bool = True

    @model_validator(mode="after")
    def _check_output(self) -> ReframeConfig:
        w, h = self.output.width, self.output.height
        if w % 2 != 0 or h % 2 != 0:
            raise ConfigError(f"reframe.output dims must be even for chroma, got {w}×{h}")
        if abs(w / h - 9 / 16) > 1e-9:
            raise ConfigError(
                f"reframe.output must be 9:16 exactly (w/h == 9/16), got {w}×{h} "
                f"(ratio {w / h:.4f})"
            )
        return self


class VideoRenderConfig(StrictModel):
    codec: str = "libx264"
    crf: int = Field(default=19, ge=0, le=51)
    preset: str = "medium"
    pix_fmt: str = "yuv420p"
    faststart: bool = True


class AudioRenderConfig(StrictModel):
    method: Literal["static_gain", "loudnorm"] = "static_gain"
    codec: str = "aac"
    target_lufs: float = Field(default=-16.0)
    target_peak: float = Field(default=-1.5)
    lra: float = Field(default=11.0)


class RenderConfig(StrictModel):
    video: VideoRenderConfig = Field(default_factory=VideoRenderConfig)
    audio: AudioRenderConfig = Field(default_factory=AudioRenderConfig)
    threads: int = Field(default=4, ge=1)
    overwrite_output: bool = True


class ReportConfig(StrictModel):
    preview_width: int = Field(default=320, ge=1)
    per_candidate_strips: int = Field(default=5, ge=1)
    include_score_table: bool = True
    embed_images: bool = True


class ScoriaConfig(StrictModel):
    version: int = Field(default=_SUPPORTED_CONFIG_VERSION, ge=1)
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    transcript: TranscriptConfig = Field(default_factory=TranscriptConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    segment: SegmentConfig = Field(default_factory=SegmentConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    captions: CaptionsConfig = Field(default_factory=CaptionsConfig)
    reframe: ReframeConfig = Field(default_factory=ReframeConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)

    @model_validator(mode="after")
    def _check_version(self) -> ScoriaConfig:
        if self.version != _SUPPORTED_CONFIG_VERSION:
            raise ConfigError(
                f"unsupported config version {self.version}; this build expects "
                f"{_SUPPORTED_CONFIG_VERSION}"
            )
        return self

    @model_validator(mode="after")
    def _check_cross_rules(self) -> ScoriaConfig:
        if self.audio.silence.min_duration > self.segment.min_duration / 10:
            raise ConfigError(
                "audio.silence.min_duration must be ≤ segment.min_duration/10 "
                f"({self.segment.min_duration / 10}), got {self.audio.silence.min_duration}"
            )
        return self
