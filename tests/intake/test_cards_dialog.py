# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cards and the dialog with Claude: a line of meta.jsonl checked against the text of its file, the digest by genre,
the seed vocabulary under the library one, the base marked behind the library after an apply, the user's documents
on the shelves of everybody (personal only on request)."""

import contextlib, io, json, types

from assistant_x.core import common, lang
from assistant_x.intake import meta_schema, review
from assistant_x.intake.tools import ocr_score
from tests.intake.intake_fixtures import doc_line

TEXT = (
    "=== page 1 ===\n\nНАЦИОНАЛЬНЫЙ СТАНДАРТ\nГОСТ Р 51858–2020\nНЕФТЬ\nОбщие технические условия\n\n"
    "=== page 2 ===\n\n# 1 Область применения\n\nНастоящий стандарт распространяется на нефть, подготовленную к "
    "транспортированию по магистральным нефтепроводам.\n\n=== page 3 ===\n\nТребования к нефти.\n"
)


def line(**kw):
    return {"T0001": doc_line("T0001", "N", "Нефть. Общие технические условия", "Oil-General-Specifications", **kw)}


def test_card_agrees_with_its_text():
    meta = line(
        designation={"ru": "ГОСТ Р 51858-2020", "en": "GOST R 51858-2020"},
        year=2020,
        keywords={"ru": ["нефть", "магистральные нефтепроводы"], "en": ["oil"]},
    )
    assert meta_schema.text_checks(meta, {"T0001": TEXT}) == ([], [])


def test_card_against_its_text_finds_what_is_wrong():
    errors, warnings = meta_schema.text_checks(
        line(designation={"ru": "ГОСТ Р 99999-2020"}, year=1999, keywords={"ru": ["сепаратор", "газ", "нефть"]}),
        {"T0001": TEXT},
    )
    assert errors == ["T0001: the designation 'ГОСТ Р 99999-2020' is not on the first 3 pages of the text"]
    assert warnings == ["T0001: the year 1999 does not occur in the text", "T0001: 1 of 3 keywords (ru) occur in the text"]
    swapped = {"T0001": doc_line("T0001", "N", "Насосы центробежные", "Pumps")}  # the line of another file
    assert meta_schema.text_checks(swapped, {"T0001": TEXT})[0] == [
        "T0001: the title shares no word with the first pages of the text: a line of another file?"
    ]


def test_the_english_short_title_is_named_plainly():
    """The top-level "en" (the file name is made from it) is not title.en: the message says which field it is."""
    meta = line()
    meta["T0001"]["en"] = ""
    (err,) = meta_schema.check(meta)
    assert 'the field "en" is missing' in err and "title.en does not replace it" in err


def test_designation_after_ocr_or_in_the_file_name():
    ocr = TEXT.replace("ГОСТ Р 51858–2020", "Г0СТ Р 51858-2020")  # OCR read the O as a zero
    meta = line(designation={"ru": "ГОСТ Р 51858-2020"}, year=2020)
    assert meta_schema.text_checks(meta, {"T0001": ocr})[0] == []  # its digits are enough
    bare = TEXT.replace("ГОСТ Р 51858–2020", "")
    assert meta_schema.text_checks(meta, {"T0001": bare})[0]
    assert meta_schema.text_checks(meta, {"T0001": bare}, {"T0001": "ГОСТ Р 51858-2020.pdf"})[0] == []


def test_digest_by_genre(tmp_path, monkeypatch):
    from assistant_x.intake.state import State

    work = tmp_path / "w"
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    t = state.add("ГОСТ Р 51858-2020.pdf", 100)
    state.update(t, status="done", pages=3)
    (work / "md" / f"{t}.md").write_text(TEXT, encoding="utf-8")
    (work / "meta_draft.jsonl").write_text(json.dumps({"tid": t, "doc_type": "standard"}) + "\n", encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        review.cmd_digest(types.SimpleNamespace(), types.SimpleNamespace(work=str(work), tids=[t]))
    text = out.getvalue()
    assert "T: НАЦИОНАЛЬНЫЙ СТАНДАРТ" in text and "scope: Область применения Настоящий стандарт" in text
    assert review.DIGEST["datasheet"][1][0] == "characteristics" and review.DIGEST["book"][1][0] == "contents"
    pages = [("1", "Обложка"), ("2", "Аннотация. Статья о сепарации нефти."), ("3", "Текст")]
    assert review.digest_part("abstract", pages, 30) == "Аннотация. Статья о сепарации"
    assert review.digest_part("characteristics", pages, 100) == ""


def test_seed_vocabulary_under_the_library_one():
    assert len(lang.vocab("en")) > 1000 and "pump" in lang.vocab("en") and lang.vocab("xx") == frozenset()
    assert len(lang.vocab_stems("en")) > 1000 and lang.vocab_stems("xx") == frozenset()
    nothing = (frozenset(), frozenset())
    assert ocr_score.known("separator", nothing) and ocr_score.known("separators", nothing)  # by its stem too
    assert not ocr_score.known("qwzrtx", nothing)
    # a new library: the seed of an open dictionary judges its words by itself (audit 6, M-015)
    assert (
        ocr_score.judged_by_vocab(nothing) and ocr_score.word_counts("qwzrtx bluvtap", nothing)[1] == 2 * ocr_score.SEED_ONLY
    )
    big = (frozenset(f"w{i}x" for i in range(ocr_score.MIN_VOCAB_WORDS)), frozenset())
    assert ocr_score.word_counts("separator qwzrtx", big)[1] == 1


def test_base_marked_behind_the_library(tmp_path):
    cfg = {"db": str(tmp_path / "db" / "library.sqlite"), "catalog": str(tmp_path / "index" / "CATALOG.md")}
    (tmp_path / "index").mkdir()
    assert common.index_stale(cfg) == "" and common.stale_note(cfg) == ""
    common.mark_index_stale(cfg, "2026-10-25")  # no base yet: a marker in the index folder
    assert (tmp_path / "index" / common.STALE_MARK).exists() and common.index_stale(cfg) == "2026-10-25"
    assert "2026-10-25" in common.stale_note(cfg) and "intake_reindex" in common.stale_note(cfg)
    (tmp_path / "db").mkdir()
    con = common.connect(cfg["db"])
    con.executescript(common.SCHEMA)
    common.clear_index_stale(cfg, con)
    con.commit()
    assert common.index_stale(cfg) == "" and not (tmp_path / "index" / common.STALE_MARK).exists()
    common.mark_index_stale(cfg, "2026-10-26")  # a base: its meta table
    assert common.index_stale(cfg) == "2026-10-26" and not (tmp_path / "index" / common.STALE_MARK).exists()
    common.clear_index_stale(cfg, con)
    con.commit()
    assert common.index_stale(cfg) == ""


def test_apply_marks_and_build_clears(project):
    from assistant_x.search import build_index
    from tests.intake.test_personal import one_document

    root, cfg = project
    one_document(cfg, "N")
    search = common.load_config(str(cfg.path))
    assert common.index_stale(search) == "2026-10-25"
    import sys

    argv = sys.argv
    sys.argv = ["build_index.py", "--config", str(cfg.path), "--no-check"]
    try:
        build_index.main()
    finally:
        sys.argv = argv
    assert common.index_stale(search) == ""


def test_personal_only_on_request(project):
    from assistant_x.core import card as C
    from assistant_x.intake import apply as intake_apply, build as intake_build, pipeline as intake
    from assistant_x.intake.state import State
    from tests.intake.test_intake_flow import GOST_MD

    root, cfg = project
    assert cfg.personal is False
    work = cfg.work / "p"
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t = state.by_rel("text.pdf")["tid"]
    (work / "md" / f"{t}.md").write_text(GOST_MD, encoding="utf-8")
    state.update(t, status="done", pages=2, ocr_pages=0)
    (work / "meta.jsonl").write_text(
        json.dumps(doc_line(t, "N", "Сепараторы нефтегазовые", "Separators")) + "\n", encoding="utf-8"
    )
    assert intake_build.build(cfg, work, date="2026-10-25", personal=True) == 0  # the user asked to keep it apart
    assert intake_apply.apply(cfg, work, date="2026-10-25") == 0
    code = json.loads((work / "codes.json").read_text(encoding="utf-8"))[t]
    assert code == "N-00002" and C.load(cfg.index / "cards" / f"{code}.json")["intake"]["personal"] is True
    assert list((cfg.library / "01_Standards").glob(f"{code}_*"))  # the same shelf and folder as every document
