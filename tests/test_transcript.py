"""Sprint 3: transcript stage — whisper JSON parse, word normalization, sentence
grouping golden, analyze_transcript wiring, analyze_video integration.

The golden fixture (`transcript_small.json`) is frozen whisper.cpp v1.9.4 `-ojf`
output (ADR-013): per-token `t_dtw` centisecond timestamps, no `words` array. The
18 words / 4 sentences it implies are the golden expectations below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scoria.config import build_config
from scoria.errors import MissingDependencyError, TranscriptError
from scoria.ingest import analyze_video
from scoria.project import build_manifest, normalize
from scoria.transcript import (
    SEGMENT_BREAK_MIN_GAP_S,
    TRANSCRIPT_SCHEMA,
    Word,
    analyze_transcript,
    group_sentences,
    load_transcript_doc,
    normalize_words,
    parse_whisper,
    run_whisper,
    whisper_cli_info,
    whisper_model_info,
)

FIXTURES = Path(__file__).parent / "fixtures"
TRANSCRIPT_SMALL = FIXTURES / "transcript_small.json"
# ADR-021 fixture: the golden `transcript-info` document saved by a whisper run —
# same 18 words / 4 sentences as `transcript_small.json`, + segment_end_indices.
TRANSCRIPT_INFO = FIXTURES / "transcript_info.json"


def _cfg(**overrides):
    data = {"media": {"min_duration": 1.0}}
    data.update(overrides)
    return build_config(overrides=data)


def _fixture_json():
    return json.loads(TRANSCRIPT_SMALL.read_text(encoding="utf-8"))


# Golden expectations computed from the fixture's t_dtw tokens (see module docstring).
GOLDEN_SENTENCES = [
    ("Apakah kalian tahu cara membuat konten?", 0.0, 1.90, 6),
    ("Viral di tiktok, tanpa effort.", 2.30, 3.65, 5),
    ("Rahasia cuma satu sip.", 5.00, 8.00, 4),
    ("Dan itu saja.", 9.50, 10.40, 3),
]
SEGMENT_END_INDICES = [2, 5, 10, 13, 14, 17]


# ---------------------------------------------------------------------------
# L0: parse_whisper — token→word reconstruction from t_dtw
# ---------------------------------------------------------------------------


def test_parse_whisper_fixture():
    language, words, ends = parse_whisper(_fixture_json())
    assert language == "id"
    assert ends == SEGMENT_END_INDICES
    assert len(words) == 18
    assert [w.text for w in words] == [
        "apakah",
        "kalian",
        "tahu",
        "cara",
        "membuat",
        "konten",
        "viral",
        "di",
        "tiktok,",
        "tanpa",
        "effort",
        "rahasia",
        "cuma",
        "satu",
        "sip",
        "dan",
        "itu",
        "saja",
    ]
    assert (words[4].start, words[4].end) == pytest.approx((1.22, 1.50))  # membuat
    assert (words[8].start, words[8].end) == pytest.approx((2.83, 3.04))  # tiktok,
    assert (words[11].start, words[11].end) == pytest.approx((5.00, 5.38))  # rahasia
    assert words[3].start == pytest.approx(0.75)  # cara is raw here; normalize snaps it


def test_parse_whisper_ignores_special_tokens_and_bad_ticks():
    raw = {
        "result": {"language": "en"},
        "transcription": [
            {
                "tokens": [
                    {"text": " [_EOT_]", "t_dtw": -1},
                    {"text": " [_BEG_]", "t_dtw": -1},
                    {"text": " hello", "t_dtw": 0},
                    {"text": "world", "t_dtw": 25},
                    {"text": " [_EOT_]", "t_dtw": -1},
                ]
            }
        ],
    }
    language, words, ends = parse_whisper(raw)
    assert language == "en"
    assert [(w.text, w.start, w.end) for w in words] == [("helloworld", 0.0, 0.25)]
    assert ends == [0]


def test_parse_whisper_skips_empty_segments_and_missing_tokens():
    raw = {
        "result": {"language": "auto"},
        "transcription": [
            {"tokens": []},
            {"text": " x", "t_dtw": 10},
        ],
    }
    _, words, ends = parse_whisper(raw)
    assert words == []
    assert ends == []


# ---------------------------------------------------------------------------
# L0: normalize_words / group_sentences
# ---------------------------------------------------------------------------


def test_normalize_words_snaps_overlaps_and_drops_empties():
    words = [
        Word(text=" a ", start=0.0, end=0.5),
        Word(text="   ", start=0.6, end=0.9),  # whitespace -> dropped
        Word(text="", start=1.0, end=1.2),  # empty -> dropped
        Word(text="b", start=0.3, end=1.0),  # start < cursor -> snapped
        Word(text="c", start=0.8, end=0.7),  # end < start -> snapped
    ]
    out = normalize_words(words)
    assert [(w.text, w.start, w.end) for w in out] == [
        ("a", 0.0, 0.5),
        ("b", 0.5, 1.0),
        ("c", 1.0, 1.0),
    ]


def test_group_sentences_golden_uses_all_three_split_rules():
    _, words, ends = parse_whisper(_fixture_json())
    words = normalize_words(words)
    sentences = group_sentences(
        words,
        max_gap_seconds=1.2,
        min_sentence_words=2,
        force_punctuation=True,
        segment_end_indices=ends,
    )
    assert [(s.text, s.start, s.end, len(s.words)) for s in sentences] == _golden_sentences()
    # question-starter (apakah) -> ?, everything else ->
    assert sentences[0].text.endswith("?")
    assert all(not s.text.endswith("?") for s in sentences[1:])
    assert all(s.text and s.text[0].isupper() for s in sentences)


def test_group_sentences_mid_sentence_trap_no_split_after_short_breath():
    _, words, ends = parse_whisper(_fixture_json())
    words = normalize_words(words)
    sentences = group_sentences(
        words,
        max_gap_seconds=1.2,
        min_sentence_words=2,
        force_punctuation=True,
        segment_end_indices=ends,
    )
    first = sentences[0]
    assert [w.text for w in first.words] == [
        "apakah",
        "kalian",
        "tahu",
        "cara",
        "membuat",
        "konten",
    ]
    assert SEGMENT_BREAK_MIN_GAP_S == 0.30  # tahu->cara gap (0.0) must not split


def test_group_sentences_merges_short_sentence_backwards():
    words = normalize_words(
        [
            Word(text="a", start=0.0, end=0.5),
            Word(text="b", start=0.6, end=1.0),
            Word(text="solo", start=5.0, end=5.5),
        ]
    )
    sentences = group_sentences(
        words,
        max_gap_seconds=1.2,
        min_sentence_words=2,
        force_punctuation=False,
        segment_end_indices=[1, 2],
    )
    assert [(s.text, s.start, s.end) for s in sentences] == [("A b solo", 0.0, 5.5)]


def test_group_sentences_ignore_whisper_segments():
    _, words, ends = parse_whisper(_fixture_json())
    words = normalize_words(words)
    with_hints = group_sentences(
        words,
        max_gap_seconds=1.2,
        min_sentence_words=2,
        force_punctuation=True,
        segment_end_indices=ends,
    )
    without = group_sentences(
        words,
        max_gap_seconds=1.2,
        min_sentence_words=2,
        force_punctuation=True,
        segment_end_indices=(),
    )
    # whisper's tahu->cara / konten->viral hints split sentences that pure gap
    # math (0.40 s gap) absorbs, so dropping the hints changes the grouping.
    assert [(s.text, len(s.words)) for s in with_hints] != [(s.text, len(s.words)) for s in without]


def test_group_sentences_disabled_punctuation_and_empty():
    words = normalize_words([Word(text="apa", start=0.0, end=1.0)])
    sentences = group_sentences(
        words, max_gap_seconds=1.2, min_sentence_words=2, force_punctuation=False
    )
    assert sentences[0].text == "Apa"  # capitalized, no mark
    empty = group_sentences([], max_gap_seconds=1.2, min_sentence_words=2, force_punctuation=True)
    assert empty == []


# ---------------------------------------------------------------------------
# L1: analyze_transcript
# ---------------------------------------------------------------------------


def _golden_sentences():
    return [
        (text, pytest.approx(start), pytest.approx(end), n)
        for text, start, end, n in GOLDEN_SENTENCES
    ]


def test_analyze_transcript_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr("scoria.transcript.pipeline.run_whisper", lambda *a, **k: _fixture_json())
    info, degraded = analyze_transcript(
        tmp_path / "in.mp4", _cfg(transcript={"enabled": True}), temp_dir=tmp_path
    )
    assert degraded == []
    assert info is not None
    assert info.document_schema == TRANSCRIPT_SCHEMA
    assert info.engine == "whisper.cpp"
    assert info.language == "id"
    assert info.model == "model/ggml-small.bin"
    assert info.model_sha256 == ""
    assert info.greedy is True
    assert info.threads == 4
    assert info.word_count == 18
    assert info.sentence_count == 4
    assert [(s.text, s.start, s.end, len(s.words)) for s in info.sentences] == _golden_sentences()


def test_analyze_transcript_segment_from_whisper_false(monkeypatch, tmp_path):
    monkeypatch.setattr("scoria.transcript.pipeline.run_whisper", lambda *a, **k: _fixture_json())
    info, degraded = analyze_transcript(
        tmp_path / "in.mp4",
        _cfg(transcript={"enabled": True, "segment_from_whisper": False}),
        temp_dir=tmp_path,
    )
    assert degraded == []
    assert info is not None
    assert info.sentence_count != 4  # whisper segment hints are ignored


def test_analyze_transcript_disabled_flag(tmp_path):
    info, degraded = analyze_transcript(
        tmp_path / "in.mp4", _cfg(transcript={"enabled": False}), temp_dir=tmp_path
    )
    assert info is None
    assert degraded == ["transcript"]


def test_analyze_transcript_no_words_is_degraded(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scoria.transcript.pipeline.run_whisper",
        lambda *a, **k: {"result": {"language": "id"}, "transcription": []},
    )
    info, degraded = analyze_transcript(
        tmp_path / "in.mp4", _cfg(transcript={"enabled": True}), temp_dir=tmp_path
    )
    assert info is None
    assert degraded == ["transcript"]


def test_analyze_transcript_missing_model_raises(tmp_path):
    cfg = _cfg(
        transcript={
            "enabled": True,
            "binary": "/bin/true",
            "model": str(tmp_path / "nope.bin"),
        }
    )
    with pytest.raises(TranscriptError, match="model not found"):
        analyze_transcript(tmp_path / "in.mp4", cfg, temp_dir=tmp_path)


def test_analyze_transcript_missing_binary_raises(tmp_path):
    cfg = _cfg(transcript={"enabled": True, "binary": "definitely-not-whisper-cli"})
    with pytest.raises(MissingDependencyError, match="not found on PATH"):
        analyze_transcript(tmp_path / "in.mp4", cfg, temp_dir=tmp_path)


# ---------------------------------------------------------------------------
# L2: analyze_video integration (transcript in analysis.json)
# ---------------------------------------------------------------------------


def test_analyze_video_writes_transcript(tmp_path, planted, monkeypatch):
    monkeypatch.setattr("scoria.transcript.pipeline.run_whisper", lambda *a, **k: _fixture_json())
    project = tmp_path / "proj"
    cfg = _cfg(project={"dir": str(project)}, transcript={"enabled": True})
    _, project_dir, degraded = analyze_video(str(planted), cfg)
    assert project_dir == project
    assert degraded == []
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    transcript = analysis["transcript"]
    assert transcript["schema"] == TRANSCRIPT_SCHEMA
    assert transcript["word_count"] == 18
    assert transcript["sentence_count"] == 4
    assert [s["text"] for s in transcript["sentences"]] == [text for text, *_ in GOLDEN_SENTENCES]


def test_analyze_video_transcript_disabled_key(tmp_path, planted):
    project = tmp_path / "proj"
    cfg = _cfg(project={"dir": str(project)}, transcript={"enabled": False})
    _, _, degraded = analyze_video(str(planted), cfg)
    assert degraded == ["transcript"]
    analysis = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["transcript"] is None


def test_analyze_video_transcript_deterministic(tmp_path, planted, monkeypatch):
    monkeypatch.setattr("scoria.transcript.pipeline.run_whisper", lambda *a, **k: _fixture_json())
    project = tmp_path / "proj"
    cfg = _cfg(project={"dir": str(project), "overwrite": True}, transcript={"enabled": True})
    analyze_video(str(planted), cfg)
    first = (project / "analysis.json").read_bytes()
    analyze_video(str(planted), cfg)
    assert (project / "analysis.json").read_bytes() == first


# ---------------------------------------------------------------------------
# Sprint 13 (ADR-021): transcript.path file ingest — load + contract-validate
# ---------------------------------------------------------------------------


def _write_doc(dir_path: Path, **overrides) -> Path:
    """Minimal but valid transcript-info doc in `dir_path`; callers override fields."""
    path = dir_path / "doc.json"
    doc = {"schema": TRANSCRIPT_SCHEMA, "words": [{"text": "a", "start": 0.0, "end": 0.5}]}
    doc.update(overrides)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_load_transcript_doc_fixture_roundtrip():
    loaded = load_transcript_doc(str(TRANSCRIPT_INFO))
    assert loaded.engine == "whisper.cpp"
    assert loaded.language == "id"
    assert loaded.model == "model/ggml-small.bin"
    assert loaded.model_sha256 == ""
    assert loaded.greedy is True
    assert loaded.threads == 4
    assert len(loaded.words) == 18
    first_words = [w.text for w in loaded.words][:6]
    assert first_words == ["apakah", "kalian", "tahu", "cara", "membuat", "konten"]
    assert loaded.segment_end_indices == SEGMENT_END_INDICES


def test_load_transcript_doc_relative_path(tmp_path, monkeypatch):
    import shutil

    doc = tmp_path / "doc.json"
    shutil.copy(TRANSCRIPT_INFO, doc)
    monkeypatch.chdir(tmp_path)
    loaded = load_transcript_doc("doc.json")
    assert loaded.language == "id"
    assert len(loaded.words) == 18


def test_load_transcript_doc_missing_file(tmp_path):
    with pytest.raises(TranscriptError, match="not found"):
        load_transcript_doc(str(tmp_path / "nope.json"))


def test_load_transcript_doc_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TranscriptError, match="cannot read"):
        load_transcript_doc(str(path))


def test_load_transcript_doc_not_an_object(tmp_path):
    path = tmp_path / "doc.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(TranscriptError, match="not a JSON object"):
        load_transcript_doc(str(path))


def test_load_transcript_doc_wrong_schema(tmp_path):
    with pytest.raises(TranscriptError, match="schema mismatch"):
        load_transcript_doc(str(_write_doc(tmp_path, schema="other")))


def test_load_transcript_doc_missing_or_empty_words(tmp_path):
    with pytest.raises(TranscriptError, match="no words"):
        load_transcript_doc(str(_write_doc(tmp_path, words=[])))
    with pytest.raises(TranscriptError, match="no words"):
        load_transcript_doc(str(_write_doc(tmp_path, words={})))


def test_load_transcript_doc_malformed_word_fields(tmp_path):
    with pytest.raises(TranscriptError, match="not an object"):
        load_transcript_doc(str(_write_doc(tmp_path, words=["a"])))
    with pytest.raises(TranscriptError, match="text/start/end"):
        load_transcript_doc(str(_write_doc(tmp_path, words=[{"text": "a"}])))
    with pytest.raises(TranscriptError, match="text/start/end"):
        load_transcript_doc(
            str(_write_doc(tmp_path, words=[{"text": "a", "start": "0", "end": 1.0}]))
        )


def test_load_transcript_doc_invalid_span(tmp_path):
    with pytest.raises(TranscriptError, match="invalid span"):
        load_transcript_doc(
            str(_write_doc(tmp_path, words=[{"text": "a", "start": 0.5, "end": 0.4}]))
        )
    with pytest.raises(TranscriptError, match="invalid span"):
        load_transcript_doc(
            str(_write_doc(tmp_path, words=[{"text": "a", "start": -1.0, "end": 0.4}]))
        )


def test_load_transcript_doc_overlapping_words(tmp_path):
    with pytest.raises(TranscriptError, match="monotonic"):
        load_transcript_doc(
            str(
                _write_doc(
                    tmp_path,
                    words=[
                        {"text": "a", "start": 0.0, "end": 1.0},
                        {"text": "b", "start": 0.5, "end": 1.5},
                    ],
                )
            )
        )


def test_load_transcript_doc_whitespace_only_words_rejected(tmp_path):
    doc = _write_doc(tmp_path, words=[{"text": "   ", "start": 0.0, "end": 1.0}])
    with pytest.raises(TranscriptError, match="no usable words"):
        load_transcript_doc(str(doc))


def test_load_transcript_doc_zero_width_words_allowed(tmp_path):
    loaded = load_transcript_doc(
        str(
            _write_doc(
                tmp_path,
                words=[
                    {"text": "a", "start": 0.0, "end": 0.0},
                    {"text": "b", "start": 0.0, "end": 0.5},
                ],
            )
        )
    )
    assert [(w.text, w.start, w.end) for w in loaded.words] == [("a", 0.0, 0.0), ("b", 0.0, 0.5)]


def test_load_transcript_doc_bad_segment_indices(tmp_path):
    words = [
        {"text": "a", "start": 0.0, "end": 0.5},
        {"text": "b", "start": 0.6, "end": 1.0},
    ]
    with pytest.raises(TranscriptError, match="strictly increasing"):
        load_transcript_doc(str(_write_doc(tmp_path, words=words, segment_end_indices=[0, 0])))
    with pytest.raises(TranscriptError, match="invalid"):
        load_transcript_doc(str(_write_doc(tmp_path, words=words, segment_end_indices=[2])))


def test_analyze_transcript_file_equals_whisper_path(monkeypatch, tmp_path):
    """ADR-021: identical words → byte-equivalent result on file and whisper paths."""
    monkeypatch.setattr("scoria.transcript.pipeline.run_whisper", lambda *a, **k: _fixture_json())
    whisper_info, wd = analyze_transcript(
        tmp_path / "in.mp4", _cfg(transcript={"enabled": True}), temp_dir=tmp_path
    )
    assert wd == []
    assert whisper_info is not None

    file_info, fd = analyze_transcript(
        tmp_path / "in.mp4",
        _cfg(transcript={"enabled": True, "path": str(TRANSCRIPT_INFO)}),
        temp_dir=tmp_path,
    )
    assert fd == []
    assert file_info is not None
    # Equal under the serialization contract: whisper computes 190·0.01 ==
    # 1.9000000000000001 while the doc stores literal 1.9 — both pin to 1.9 on
    # write, so the on-disk analysis.json (and every downstream artifact) is
    # byte-identical between the two paths.
    assert normalize(file_info.model_dump()) == normalize(whisper_info.model_dump())


def test_analyze_transcript_file_never_runs_whisper(monkeypatch, tmp_path):
    def _explode(*a, **k):
        raise AssertionError("run_whisper must not be called for transcript.path ingest")

    monkeypatch.setattr("scoria.transcript.pipeline.run_whisper", _explode)
    info, degraded = analyze_transcript(
        tmp_path / "in.mp4",
        _cfg(transcript={"enabled": True, "path": str(TRANSCRIPT_INFO)}),
        temp_dir=tmp_path,
    )
    assert degraded == []
    assert info is not None
    assert info.word_count == 18 and info.sentence_count == 4
    assert info.engine == "whisper.cpp"  # provenance carried from the document
    assert info.model == "model/ggml-small.bin"
    assert info.segment_end_indices == SEGMENT_END_INDICES


def test_analyze_transcript_file_hints_off(monkeypatch, tmp_path):
    info, degraded = analyze_transcript(
        tmp_path / "in.mp4",
        _cfg(
            transcript={
                "enabled": True,
                "path": str(TRANSCRIPT_INFO),
                "segment_from_whisper": False,
            }
        ),
        temp_dir=tmp_path,
    )
    assert degraded == []
    assert info is not None
    assert info.word_count == 18
    assert info.segment_end_indices == []


def test_analyze_transcript_file_broken_doc_raises(tmp_path):
    cfg = _cfg(transcript={"enabled": True, "path": str(tmp_path / "missing.json")})
    with pytest.raises(TranscriptError, match="not found"):
        analyze_transcript(tmp_path / "in.mp4", cfg, temp_dir=tmp_path)


# ---------------------------------------------------------------------------
# tool info (manifest stamps)
# ---------------------------------------------------------------------------


def test_manifest_transcript_source_stamp():
    tools = {"ffmpeg": None}
    invocation = ["clipper", "run", "x.mp4"]
    disabled = build_manifest(
        config=_cfg(transcript={"enabled": False}), tools=tools, invocation=invocation
    )
    assert disabled["transcript_source"] is None
    whisper = build_manifest(
        config=_cfg(transcript={"enabled": True}), tools=tools, invocation=invocation
    )
    assert whisper["transcript_source"] == "whisper.cpp"
    file_doc = build_manifest(
        config=_cfg(transcript={"enabled": True, "path": str(TRANSCRIPT_INFO)}),
        tools=tools,
        invocation=invocation,
    )
    assert file_doc["transcript_source"] == "file"


def test_envcheck_reports_transcript_file_tool(tmp_path, monkeypatch):
    import scoria.envcheck as envcheck

    cfg = _cfg(transcript={"enabled": True, "path": str(TRANSCRIPT_INFO)})
    monkeypatch.setattr("scoria.envcheck.build_config", lambda: cfg)
    report = envcheck.check()
    assert report["tools"]["transcript_file"]["present"] is True
    assert report["tools"]["transcript_file"]["version"] == "whisper.cpp"
    assert report["tools"]["transcript_file"]["binary"] == str(TRANSCRIPT_INFO)
    # default config (no path) never shows the tool
    monkeypatch.setattr("scoria.envcheck.build_config", lambda: _cfg(transcript={"enabled": True}))
    assert "transcript_file" not in envcheck.check()["tools"]


def test_envcheck_transcript_file_missing(tmp_path, monkeypatch):
    import scoria.envcheck as envcheck

    missing = tmp_path / "nope.json"
    cfg = _cfg(transcript={"enabled": True, "path": str(missing)})
    monkeypatch.setattr("scoria.envcheck.build_config", lambda: cfg)
    tool = envcheck.check()["tools"]["transcript_file"]
    assert tool["present"] is False
    assert tool["binary"] == str(missing)


def test_whisper_cli_info_none_when_missing():
    cfg = _cfg(transcript={"binary": "definitely-not-whisper-cli"})
    assert whisper_cli_info(cfg.transcript) is None


def test_whisper_model_info_missing_file(tmp_path):
    info = whisper_model_info(_cfg(transcript={"model": str(tmp_path / "missing.bin")}).transcript)
    assert info == {"path": str(tmp_path / "missing.bin"), "sha256": ""}


# ---------------------------------------------------------------------------
# env-gated real-bridge smoke (ADR-014): skipped unless SCORIA_WHISPER_BIN +
# SCORIA_WHISPER_MODEL are set. Exercises the full decode -> whisper-cli -> parse path.
# ---------------------------------------------------------------------------

_WHISPER_ENV_READY = bool(os.environ.get("SCORIA_WHISPER_BIN")) and bool(
    os.environ.get("SCORIA_WHISPER_MODEL")
)


@pytest.mark.skipif(
    not _WHISPER_ENV_READY,
    reason="set SCORIA_WHISPER_BIN + SCORIA_WHISPER_MODEL to run the real-bridge smoke",
)
def test_real_whisper_bridge_smoke(planted_wav, tmp_path):
    cfg = _cfg(
        transcript={
            "enabled": True,
            "binary": os.environ["SCORIA_WHISPER_BIN"],
            "model": os.environ["SCORIA_WHISPER_MODEL"],
            "language": "auto",
            "threads": 4,
        }
    )
    raw = run_whisper(planted_wav, config=cfg, temp_dir=tmp_path)
    assert "transcription" in raw
    language, words, ends = parse_whisper(raw)
    assert language is not None
    assert len(ends) <= len(words)  # one hint per non-empty segment
    assert (tmp_path / "planted_silence-whisper.wav").exists() is False  # cleaned up
