"""Self-contained `report.html` generator: inline CSS, no JS, webfont-free.

Pure renderer: the previews document + ranking + config in, one HTML string out.
Images are embedded as base64 `data:` URIs when `report.embed_images` is true
(the default single self-contained file), otherwise linked relatively to
`previews/`. No timestamps are emitted, so `report.html` is byte-stable for the
same inputs (determinism contract).
"""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any

from scoria.config.schema import ScoriaConfig

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 1100px; padding: 24px; background: #0b0e13;
  color: #e6edf3; font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; border-bottom: 1px solid #2b3440; padding-bottom: 4px; }
.meta { color: #9aa7b4; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 4px 10px 4px 0; border-bottom: 1px solid #1e2731; }
th { color: #9aa7b4; font-weight: normal; }
.num { text-align: right; }
.timeline { display: block; margin: 8px 0 0; }
.clip { margin: 18px 0; padding: 12px; background: #11151c; border: 1px solid #1e2731;
  border-radius: 6px; }
.clip header { margin-bottom: 8px; color: #9aa7b4; }
.clip img { display: block; max-width: 100%; height: auto; margin: 6px 0;
  border: 1px solid #2b3440; border-radius: 4px; }
footer { margin-top: 32px; color: #6b7684; font-size: 12px; }
"""


def _img_src(project_dir: Path, rel_path: str, *, embed: bool) -> str:
    src = Path(rel_path)
    if embed:
        data = base64.b64encode((project_dir / src).read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    return html.escape(src.as_posix())


def _score_table(ranking: dict[str, Any]) -> str:
    rows = []
    for clip in ranking.get("selected", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(clip.get('rank')))}</td>"
            f"<td>{html.escape(str(clip.get('id')))}</td>"
            f'<td class="num">{float(clip.get("start", 0.0)):.3f}</td>'
            f'<td class="num">{float(clip.get("end", 0.0)):.3f}</td>'
            f'<td class="num">{float(clip.get("duration", 0.0)):.3f}</td>'
            f'<td class="num">{float(clip.get("score", 0.0)):.4f}</td>'
            f'<td class="num">{float(clip.get("gain", 0.0)):.4f}</td>'
            "</tr>"
        )
    header = (
        '<tr><th>#</th><th>clip</th><th class="num">start</th>'
        '<th class="num">end</th><th class="num">dur</th>'
        '<th class="num">score</th><th class="num">gain</th></tr>'
    )
    return f"<table><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"


def render_report_html(
    *,
    previews: dict[str, Any],
    ranking: dict[str, Any],
    cfg: ScoriaConfig,
    project_dir: Path,
) -> str:
    """Compose the self-contained report page from preview assets + ranking."""
    embed = cfg.report.embed_images
    timeline_file = previews.get("timeline", {}).get("file", "")
    timeline_svg = (
        (project_dir / timeline_file).read_text(encoding="utf-8").strip() if timeline_file else ""
    )

    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>scoria report</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        "<h1>scoria report</h1>",
        (
            f'<div class="meta">{html.escape(str(previews.get("source", "")))}'
            f" — {float(previews.get('media_duration', 0.0)):.3f}s — "
            f"{len(previews.get('clips', []))} clip(s) — "
            f"preview {html.escape(str(previews.get('preview_version', '')))}"
            f"</div>"
        ),
    ]
    if timeline_svg:
        parts.append("<h2>Timeline</h2>")
        parts.append(f'<div class="timeline">{timeline_svg}</div>')
    if cfg.report.include_score_table:
        parts.append("<h2>Scores</h2>")
        parts.append(_score_table(ranking))
    parts.append("<h2>Clips</h2>")
    for clip in previews.get("clips", []):
        thumb = _img_src(project_dir, str(clip["thumbnail"]), embed=embed)
        sheet = _img_src(project_dir, str(clip["contact_sheet"]), embed=embed)
        times = ", ".join(f"{float(t):.3f}s" for t in clip.get("strip_times", []))
        parts.append(
            f'<div class="clip"><header>#{html.escape(str(clip["rank"]))} '
            f"{html.escape(str(clip['id']))} — "
            f"{float(clip['start']):.3f}s..{float(clip['end']):.3f}s — "
            f"sheet frames: {html.escape(times)}</header>"
            f'<img src="{thumb}" alt="{html.escape(str(clip["id"]))} thumbnail">'
            f'<img src="{sheet}" alt="{html.escape(str(clip["id"]))} contact sheet">'
            "</div>"
        )
    parts.append(
        "<footer>scoria · deterministic, local-first clipping · "
        "no network, no analysis rerun</footer>"
    )
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"
