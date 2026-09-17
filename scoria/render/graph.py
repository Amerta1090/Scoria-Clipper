"""Pure filter-graph + audio-gain math for render (Sprint 9).

These functions are deterministic closed-form: ReframePlan geometry → ffmpeg
filter strings, measured LUFS → static gain (ADR-005). No subprocess, no IO —
everything here is unit-testable pure math (rendering decides *what* to build;
`core.py` decides *when* to run it).
"""

from __future__ import annotations

from pathlib import Path

from scoria.reframe.models import ReframePlan

BLUR_RADIUS = 20
BLUR_STRENGTH = 4


def audio_gain_db(
    measured_lufs: float | None,
    *,
    target_lufs: float,
    target_peak: float,
    measured_peak: float | None = None,
) -> float:
    """Static linear gain in dB toward `target_lufs`, capped by peak headroom.

    ADR-005: normalization is a deterministic linear gain from the measured
    integrated loudness (ebur128 pass), not dynamic `loudnorm`. No measured
    loudness → 0 dB (pass-through). The result is rounded to the 4-decimal
    serialization contract so the applied `volume=…dB` filter is exact on the
    wire and in render.json.
    """
    if measured_lufs is None:
        return 0.0
    gain = target_lufs - measured_lufs
    if measured_peak is not None:
        headroom = target_peak - measured_peak
        gain = min(gain, headroom)
    return round(float(gain), 4)


def escape_filter_path(path: Path) -> str:
    """Escape a file path for use inside an ffmpeg filter argument value.

    The `subtitles`/`ass` filter parses `filename=` with `:`, `,`, `'`, `[`, `]`
    as separators; separators are normalized to `/` and the specials are
    backslash-escaped so an absolute path survives the graph parser.
    """
    value = str(path).replace("\\", "/")
    for special in (":", "'", ",", "[", "]"):
        value = value.replace(special, f"\\{special}")
    return value


def build_video_chain(plan: ReframePlan):
    """Map a ReframePlan to (filter_complex, vf, map_label).

    - strategy `scale`:   plain `-vf scale=W:H`, stream map `0:v:0`
    - strategy `crop`:    plain `-vf crop=w:h:x:y,scale=W:H`, stream map `0:v:0`
    - strategy `blur_pad`: filter_complex split → blurred full-frame backdrop +
      contain-scaled content overlay (Sprint 9 graph from Sprint 8's L3 stub);
      requires the explicit `-map [vout]` label.

    Note: no `format=yuv420p` is passed to `overlay` — this ffmpeg build (9.0.1)
    rejects it (Sprint 8 drift), and overlay defaults are yuv420p-compatible.
    """
    out_w, out_h = plan.output.width, plan.output.height
    if plan.strategy == "scale":
        return None, f"scale={out_w}:{out_h}", None
    if plan.strategy == "crop":
        crop = plan.crop
        chain = f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y},scale={out_w}:{out_h}"
        return None, chain, None
    content = plan.content
    pad = plan.pad
    fc = (
        "split=2[bg][fg];"
        f"[bg]scale={out_w}:{out_h},boxblur={BLUR_RADIUS}:{BLUR_STRENGTH}[bg2];"
        f"[fg]scale={content.width}:{content.height}[fg2];"
        f"[bg2][fg2]overlay={pad.left}:{pad.top}[vout]"
    )
    return fc, None, "[vout]"


def with_burn(fc: str | None, vf: str | None, label: str | None, ass_path: Path):
    """Append the libass `subtitles` burn stage to a chain.

    Returns the same (filter_complex, vf, map_label) triple with the burn stage
    as the final filter and an updated map label when the chain is complex.
    """
    sub = f"subtitles=filename={escape_filter_path(ass_path)}"
    if fc is not None:
        target = label or "[vout]"
        return f"{fc};{target}{sub}[vout2]", None, "[vout2]"
    return None, f"{vf},{sub}" if vf else sub, None


def filters_string(fc: str | None, vf: str | None) -> str:
    """Human-readable filters record for render.json (the effective graph)."""
    return fc or vf or ""
