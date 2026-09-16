"""Sprint 7: captions — line builder, SRT/ASS writers, karaoke, CLI.

L0 pins the pure line-builder math (window clamping, max_duration chunks,
max_lines / chars_per_line wrapping, sentence-break reflow, min_word_count);
L1 pins the writers (golden SRT/ASS strings, timestamp formats, karaoke ==
word spans, parse-back round-trip); L5 pins `clipper captions` (sidecars,
errors, determinism). The acceptance test asserts every caption ≤ max_duration
and every line ≤ chars_per_line over a dense stress input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scoria.captions import (
    CAPTION_VERSION,
    CAPTIONS_SCHEMA,
    CAPTIONS_VERSION,
    build_captions,
    build_clip_captions,
    format_ass_timestamp,
    format_srt_timestamp,
    write_ass,
    write_srt,
)
from scoria.captions.lines import chunk_by_duration, clamp_words
from scoria.captions.models import Caption
from scoria.cli.main import app
from scoria.config import build_config
from scoria.config.schema import CaptionsConfig
from scoria.errors import ConfigError
from scoria.project import check_contract, dump_str
from scoria.transcript.models import Word

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS_SMALL = FIXTURES / "analysis_small.json"

runner = CliRunner()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _word(start: float, end: float, text: str) -> Word:
    return Word(text=text, start=start, end=end)


def _cfg(**kw) -> CaptionsConfig:
    defaults = dict(
        enabled=True,
        format=["srt", "ass"],
        burn_in=True,
        chars_per_line=42,
        max_lines=2,
        max_duration=5.1,
        min_word_count=1,
        prefer_sentence_breaks=True,
        wpm=200,
    )
    defaults.update(kw)
    return CaptionsConfig(**defaults)


# ---------------------------------------------------------------------------
# L0: line builder — window clamping
# ---------------------------------------------------------------------------


def test_clamp_words_keeps_window_and_clips_boundary_words():
    words = [
        _word(0.0, 1.0, "before"),
        _word(1.0, 2.0, "straddles-start"),  # clipped to [1.5, 2.0)
        _word(2.0, 3.0, "inside"),
        _word(3.0, 4.0, "straddles-end"),  # clipped to [3.0, 3.5)
        _word(4.0, 5.0, "after"),
    ]
    clamped = clamp_words(words, 1.5, 3.5)
    assert [(w.text, w.start, w.end) for w in clamped] == [
        ("straddles-start", 1.5, 2.0),
        ("inside", 2.0, 3.0),
        ("straddles-end", 3.0, 3.5),
    ]


def test_clamp_words_drops_zero_overlap():
    words = [_word(1.5, 1.5, "zero"), _word(2.0, 1.0, "negative")]
    assert clamp_words(words, 0.0, 5.0) == []


# ---------------------------------------------------------------------------
# L0: duration chunking
# ---------------------------------------------------------------------------


def test_chunk_by_duration_respects_max_duration():
    words = [_word(i * 0.7, i * 0.7 + 0.5, f"w{i}") for i in range(6)]
    chunks = chunk_by_duration(words, max_duration=2.0)
    for chunk in chunks:
        assert chunk[-1].end - chunk[0].start <= 2.0
    assert [len(c) for c in chunks] == [3, 3]


def test_single_word_span_exceeds_max_duration_stays_whole():
    words = [_word(0.0, 3.0, "longword")]
    chunks = chunk_by_duration(words, max_duration=2.0)
    assert chunks == [words]


# ---------------------------------------------------------------------------
# L0: line wrapping + block shape
# ---------------------------------------------------------------------------


def test_lines_never_exceed_chars_per_line():
    words = [_word(i, i + 0.4, f"word{i:02d}") for i in range(20)]
    blocks = build_clip_captions(words, 0.0, 20.0, _cfg(chars_per_line=12, max_lines=3))
    assert blocks
    for block in blocks:
        assert len(block.lines) <= 3
        for line in block.lines:
            assert len(line) <= 12


def test_max_duration_bound_over_dense_speech():
    words = []
    t = 0.0
    for i in range(30):  # continuous speech, no gaps
        words.append(_word(t, t + 0.3, f"w{i}"))
        t += 0.3
    blocks = build_clip_captions(words, 0.0, 9.0, _cfg(max_duration=2.0, wpm=600))
    assert blocks
    for block in blocks:
        assert block.end - block.start <= 2.0 + 1e-9


def test_sentence_break_reflow_prefers_sentence_end():
    words = [
        _word(0.0, 0.5, "Hello"),
        _word(0.5, 1.0, "there."),
        _word(1.0, 1.5, "how"),
        _word(1.5, 2.0, "are"),
        _word(2.0, 2.5, "you"),
        _word(2.5, 3.0, "today?"),
    ]
    preferred = build_clip_captions(words, 0.0, 3.0, _cfg(chars_per_line=20))
    assert preferred[0].lines == ["Hello there.", "how are you today?"]
    plain = build_clip_captions(
        words, 0.0, 3.0, _cfg(chars_per_line=20, prefer_sentence_breaks=False)
    )
    assert plain[0].lines == ["Hello there. how are", "you today?"]


def test_min_word_count_drops_short_blocks():
    words = [
        _word(0.0, 0.4, "solo"),
        _word(2.0, 2.4, "pair"),
        _word(4.0, 4.4, "two"),
    ]
    # max_duration 1.0 with ≥2 s gaps → every chunk is a single word
    blocks = build_clip_captions(
        words, 0.0, 5.0, _cfg(max_duration=1.0, wpm=1200, min_word_count=2)
    )
    assert blocks == []


def test_build_clip_captions_keeps_two_word_blocks_at_min_word_count_2():
    words = [
        _word(0.0, 0.4, "one"),
        _word(0.4, 0.8, "two"),
        _word(2.0, 2.4, "three"),
        _word(2.4, 2.8, "four"),
    ]
    blocks = build_clip_captions(
        words, 0.0, 3.0, _cfg(max_duration=1.0, wpm=1200, min_word_count=2)
    )
    assert len(blocks) == 2
    assert all(b.word_count >= 2 for b in blocks)


def test_build_clip_captions_window_times_and_deterministic():
    words = [
        _word(0.0, 0.5, "one"),
        _word(0.5, 1.0, "two"),
        _word(1.0, 1.5, "three"),
    ]
    first = build_clip_captions(words, 0.25, 1.25, _cfg())
    second = build_clip_captions(words, 0.25, 1.25, _cfg())
    assert first[0].start == 0.25  # first word clipped to the window start
    assert first[-1].end == 1.25  # last word clamped to the window end
    assert [b.model_dump() for b in first] == [b.model_dump() for b in second]


# ---------------------------------------------------------------------------
# L1: writers — timestamp formats
# ---------------------------------------------------------------------------


def test_srt_timestamp_format():
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(1.5) == "00:00:01,500"
    assert format_srt_timestamp(61.5) == "00:01:01,500"
    assert format_srt_timestamp(3661.5) == "01:01:01,500"


def test_ass_timestamp_format():
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(1.5) == "0:00:01.50"
    assert format_ass_timestamp(61.5) == "0:01:01.50"
    assert format_ass_timestamp(3661.5) == "1:01:01.50"


# ---------------------------------------------------------------------------
# L1: golden SRT / ASS strings
# ---------------------------------------------------------------------------


def _sample_captions() -> list[Caption]:
    """[0, 4.5) window, one block with one line — pinned golden below."""
    words = [
        _word(0.0, 0.8, "Hello"),
        _word(0.8, 1.6, "world."),
        _word(2.4, 3.0, "This"),
        _word(3.0, 3.4, "is"),
        _word(3.4, 3.7, "a"),
        _word(3.7, 4.5, "test."),
    ]
    return build_clip_captions(words, 0.0, 4.5, _cfg())


def test_srt_golden_string():
    text = write_srt(_sample_captions())
    assert text == "1\n00:00:00,000 --> 00:00:04,500\nHello world. This is a test.\n\n"


def test_ass_golden_string():
    text = write_ass(_sample_captions(), _cfg().ass_style)
    assert text == (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Caption,DejaVu Sans,58,&H00FFFFFF,&H0000FFFF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,10,10,160,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:04.50,Caption,,0,0,0,,"
        "{\\k80}Hello {\\k80}world. {\\k60}This {\\k40}is {\\k30}a {\\k80}test.\n"
    )


def test_srt_parse_back_roundtrip():
    captions = _sample_captions()
    parsed = _parse_srt(write_srt(captions))
    assert [(p[0], p[1], p[2]) for p in parsed] == [(c.start, c.end, c.lines) for c in captions]


def _parse_srt(text: str) -> list[tuple[float, float, list[str]]]:
    blocks = []
    for chunk in text.strip().split("\n\n"):
        lines = chunk.split("\n")
        start_s, end_s = (part.strip() for part in lines[1].split("-->"))
        blocks.append((_parse_srt_time(start_s), _parse_srt_time(end_s), lines[2:]))
    return blocks


def _parse_srt_time(value: str) -> float:
    hours, minutes, rest = value.split(":")
    secs, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000


# ---------------------------------------------------------------------------
# L1: karaoke == word spans
# ---------------------------------------------------------------------------


def test_ass_karaoke_equals_word_spans():
    captions = _sample_captions()
    text = write_ass(captions, _cfg().ass_style)
    tag_values = [int(m) for m in __import__("re").findall(r"\\k(\d+)", text)]
    expected = [round((w.end - w.start) * 100) for c in captions for w in c.words]
    assert tag_values == expected
    # no unresolved karaoke: every word is tagged exactly once
    words_in_text = [w.text for c in captions for w in c.words]
    assert text.count("\\k") == len(words_in_text)


def test_ass_karaoke_disabled_uses_line_breaks():
    style = _cfg().ass_style.model_copy(update={"karaoke_words": False})
    words = [
        _word(0.0, 0.5, "Hello"),
        _word(0.5, 1.0, "there."),
        _word(1.0, 1.5, "how"),
        _word(1.5, 2.0, "are"),
        _word(2.0, 2.5, "you"),
        _word(2.5, 3.0, "today?"),
    ]
    captions = build_clip_captions(words, 0.0, 3.0, _cfg(chars_per_line=20))
    assert len(captions[0].lines) == 2
    dialog = write_ass(captions, style).splitlines()[-1]
    assert "\\k" not in dialog
    assert "\\N" in dialog


# ---------------------------------------------------------------------------
# L1: empty input
# ---------------------------------------------------------------------------


def test_writers_empty_input():
    assert write_srt([]) == ""
    header = write_ass([], _cfg().ass_style)
    assert "[Script Info]" in header and "[Events]" in header
    assert "Dialogue:" not in header


# ---------------------------------------------------------------------------
# L1: config readability rule (ADR-018)
# ---------------------------------------------------------------------------


def test_default_captions_config_passes_readability_rule():
    cfg = _cfg()
    assert cfg.max_duration >= (cfg.chars_per_line * cfg.max_lines / 5.0) / (cfg.wpm / 60.0)


def test_readability_rule_rejects_contradicting_defaults():
    with pytest.raises(ConfigError, match="readability"):
        CaptionsConfig(max_duration=4.5, chars_per_line=42, max_lines=2, wpm=200)


def test_readability_rule_accepts_exact_minimum():
    cfg = _cfg(max_duration=5.04, wpm=200)  # (42*2/5)/(200/60) == 5.04
    assert cfg.max_duration >= 5.04 - 1e-9


# ---------------------------------------------------------------------------
# L2: build_captions doc contract
# ---------------------------------------------------------------------------


def test_build_captions_doc_contract(tmp_path):
    analysis = json.loads(ANALYSIS_SMALL.read_text(encoding="utf-8"))
    ranking = {
        "schema": "ranking",
        "selected": [
            {"id": "c0006", "rank": 1, "start": 12.0, "end": 70.0},
            {"id": "c0014", "rank": 2, "start": 80.0, "end": 120.0},
        ],
    }
    doc = build_captions(ranking, analysis, build_config())
    dumped = json.loads(dump_str(doc))
    assert dumped["schema"] == CAPTIONS_SCHEMA
    assert dumped["version"] == CAPTIONS_VERSION
    assert dumped["caption_version"] == CAPTION_VERSION
    assert [clip["id"] for clip in dumped["clips"]] == ["c0006", "c0014"]
    assert check_contract(dumped) == []
    for clip in dumped["clips"]:
        for block in clip["captions"]:
            # single-word blocks may exceed max_duration (words are never split,
            # ADR-018 edge case); multi-word blocks must respect it
            if len(block["words"]) != 1:
                assert block["end"] - block["start"] <= build_config().captions.max_duration + 1e-9


# ---------------------------------------------------------------------------
# L5: `clipper captions`
# ---------------------------------------------------------------------------


def _write_project(tmp_path) -> Path:
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(
        json.dumps(json.loads(ANALYSIS_SMALL.read_text(encoding="utf-8"))), encoding="utf-8"
    )
    candidates_path = tmp_path / "candidates.json"
    from scoria.segment import build_candidates

    candidates = build_candidates(
        json.loads(analysis_path.read_text(encoding="utf-8")), build_config()
    )
    candidates_path.write_text(dump_str(candidates), encoding="utf-8")
    return candidates_path


def _ranked_project(tmp_path) -> Path:
    candidates = _write_project(tmp_path)
    scored = runner.invoke(app, ["score", str(candidates), "--log-level", "error"])
    assert scored.exit_code == 0, scored.output
    ranked = runner.invoke(app, ["rank", str(candidates), "--top", "3", "--log-level", "error"])
    assert ranked.exit_code == 0, ranked.output
    return tmp_path / "ranking.json"


def test_cli_captions_writes_sidecars(tmp_path):
    ranking = _ranked_project(tmp_path)
    result = runner.invoke(app, ["captions", str(ranking), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    out_dir = tmp_path / "captions"
    assert (out_dir / "captions.json").is_file()
    assert (out_dir / "c0006.srt").is_file()
    assert (out_dir / "c0006.ass").is_file()
    assert (out_dir / "c0014.srt").is_file()
    assert (out_dir / "c0014.ass").is_file()
    doc = json.loads((out_dir / "captions.json").read_text(encoding="utf-8"))
    assert doc["schema"] == CAPTIONS_SCHEMA
    assert check_contract(doc) == []


def test_cli_captions_accepts_project_dir(tmp_path):
    _ranked_project(tmp_path)
    result = runner.invoke(app, ["captions", str(tmp_path), "--log-level", "error"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "captions" / "captions.json").is_file()


def test_cli_captions_json_summary(tmp_path):
    ranking = _ranked_project(tmp_path)
    result = runner.invoke(app, ["captions", str(ranking), "--json", "--log-level", "error"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output.strip().splitlines()[-1])
    assert summary["clips"] == 2
    assert summary["captions"] > 0
    assert summary["caption_version"] == CAPTION_VERSION
    assert summary["captions_version"] == CAPTIONS_VERSION
    assert len(summary["files"]) == 4


def test_cli_captions_requires_ranking_document(tmp_path):
    candidates = _write_project(tmp_path)
    result = runner.invoke(app, ["captions", str(candidates), "--log-level", "error"])
    assert result.exit_code == 1
    assert "schema != 'ranking'" in result.output


def test_cli_captions_requires_transcript(tmp_path):
    ranking = _ranked_project(tmp_path)
    analysis_path = tmp_path / "analysis.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis.pop("transcript", None)
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    result = runner.invoke(app, ["captions", str(ranking), "--log-level", "error"])
    assert result.exit_code == 1
    assert "no transcript" in result.output


def test_cli_captions_requires_word_timestamps(tmp_path):
    ranking = _ranked_project(tmp_path)
    analysis_path = tmp_path / "analysis.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis["transcript"]["words"] = []
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    result = runner.invoke(app, ["captions", str(ranking), "--log-level", "error"])
    assert result.exit_code == 1
    assert "no word timestamps" in result.output


def test_cli_captions_deterministic(tmp_path):
    ranking = _ranked_project(tmp_path)
    for _ in range(2):
        assert runner.invoke(app, ["captions", str(ranking), "--log-level", "error"]).exit_code == 0
    out_dir = tmp_path / "captions"
    first = {p.name: p.read_bytes() for p in out_dir.iterdir() if p.is_file()}
    assert runner.invoke(app, ["captions", str(ranking), "--log-level", "error"]).exit_code == 0
    second = {p.name: p.read_bytes() for p in out_dir.iterdir() if p.is_file()}
    assert first == second
