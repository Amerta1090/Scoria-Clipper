"""Docs integrity: every relative markdown link in the docs corpus resolves on disk."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MD_FILES = sorted(
    [
        *list((REPO / "docs").glob("*.md")),
        REPO / "README.md",
        REPO / "prompt.md",
        REPO / "CHANGELOG.md",
    ]
)

_LINK_RE = re.compile(r"\]\(([^)#\s]+?)(?:#[^)]*)?\)")


def test_relative_markdown_links_resolve():
    broken = []
    for md in MD_FILES:
        text = md.read_text(encoding="utf-8")
        for target in _LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            candidate = (md.parent / target).resolve()
            if not candidate.is_file():
                broken.append(f"{md.relative_to(REPO)} -> {target}")
    assert not broken, "broken relative markdown links:\n" + "\n".join(broken)
