# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of the card draft found wrong by the first real batch (audit 6): a designation the document only cites,
"OST" inside "GOST", truncated numbers, a title from a page of authors, the genre of a slide deck, a contents made of
picture names, the order of the parts of a book in many files, the draft of a file written as soon as it is done."""

import json

import pytest

from assistant_x.core.formats import natural_key
from assistant_x.intake import build, meta_schema, metadraft, prepare
from assistant_x.intake.state import State


def page(n, text):
    return f"=== page {n} ===\n\n{text}\n"


# ---------- designations ----------


@pytest.mark.parametrize(
    "text, want",
    [
        ("ГОСТ 12124-80", ["ГОСТ 12124-80"]),  # one reference, no "ОСТ 12124-80" inside it
        ("по ГОСТ 8.417-81 и ГОСТ 12.2.063-2015", ["ГОСТ 8.417-81", "ГОСТ 12.2.063-2015"]),
        ("ГОСТ 12.2.0632015", []),  # the year glued to the number by OCR: no designation
        ("РД 0 и СП 2", []),  # pieces of a line
        ("СП 231.1311500.2015", ["СП 231.1311500.2015"]),  # a long group that is a number
        ("ОСТ 39-225-88", ["ОСТ 39-225-88"]),
    ],
)
def test_references(text, want):
    assert [r["designation"] for r in metadraft.references(text)] == want


def test_a_book_citing_a_standard_is_no_standard():
    """Markin's book cites a GOST in its preface: the designation is a reference, the genre is a book (M-021)."""
    md = page(1, "А. Н. МАРКИН\n\nНЕФТЕПРОМЫСЛОВАЯ ХИМИЯ\n\nМосква: Недра, 2005") + page(
        2, "Предисловие\n\nТребования к реагентам приведены в соответствии с\nГОСТ 12.2.063-2015 и другими документами."
    )
    d = metadraft.draft(md, "Маркин.pdf")
    assert "designation" not in d and d["doc_type"] == "book"
    assert {"designation": "ГОСТ 12.2.063-2015"} in d["references"]


def test_own_designation_of_a_standard():
    pages = ["НАЦИОНАЛЬНЫЙ СТАНДАРТ\nРОССИЙСКОЙ ФЕДЕРАЦИИ\n\nГОСТ Р 51858-2002\n\nНЕФТЬ\nОбщие технические условия"]
    assert metadraft.own_designation(pages) == "ГОСТ Р 51858-2002"
    assert metadraft.own_designation(["Требования ГОСТ 1234-80 обязательны"]) is None  # inside a sentence
    assert metadraft.own_designation(["a", "b", "ГОСТ 1234-80"]) is None  # only the first two pages


# ---------- title and genre ----------


def test_title_skips_a_page_of_names():
    pages = [
        "Редакционный совет:\nИванов И. И., Петров П. П.\nСидоров С. С.\nКозлов К. К.",
        "ТЕХНОЛОГИЯ ПОДГОТОВКИ ГАЗА\nУчебное пособие",
    ]
    assert metadraft.title_of(pages) == "Технология подготовки газа"
    assert (
        metadraft.title_of(["ISBN 978-5-00-000000-0\nНаучный редактор\nСЕПАРАЦИЯ НЕФТИ И ГАЗА"]) == "Сепарация нефти и газа"
    )


@pytest.mark.parametrize("ext, want", [("pptx", "presentation"), ("ppt", "presentation"), ("xlsx", "dataset")])
def test_genre_by_format(ext, want):
    assert metadraft.doc_type_of("УСТАНОВКАОСУШКИГАЗА", None, ext) == want
    assert metadraft.draft(page(1, "УСТАНОВКА ОСУШКИ ГАЗА"), f"slides.{ext}")["doc_type"] == want


# ---------- contents ----------


def test_contents_without_picture_names_and_with_chapter_titles():
    pages = [
        (1, "# Глава 1\n\nСепарация нефти и газа\n\nтекст"),
        (2, "# img_12.png\n\nтекст"),
        (3, "# Глава 2\n\nОсушка природного газа\n\nтекст"),
        (4, "# Глава 3\n\nОчистка газа от сероводорода\n\nтекст"),
    ]
    toc, _ = metadraft.contents(pages)
    titles = [t["title"] for t in toc]
    assert titles == [
        "Глава 1. Сепарация нефти и газа",
        "Глава 2. Осушка природного газа",
        "Глава 3. Очистка газа от сероводорода",
    ]


def test_noisy_contents_left_out():
    """Lines that all point to one page, or most of them service lines: no contents is better than a wrong one."""
    same = [(1, "# Москва, 2005\n# Издательство Недра\n# Редакционный совет\n# Глава")] + [(i, "текст") for i in range(2, 6)]
    assert metadraft.contents(same)[0] == []


def test_heading_ok():
    assert metadraft.heading_ok("5.3 Сепараторы")
    assert metadraft.heading_ok("Осушка природного газа")
    assert metadraft.heading_ok("Введение")  # one word of a contents page
    assert not metadraft.heading_ok("Глава 3")  # a chapter without its title
    assert not metadraft.heading_ok("img_3.png")
    assert not metadraft.heading_ok("2005")
    assert not metadraft.heading_ok("Москва, 2005")
    assert not metadraft.heading_ok("ΔT = T1 - T2")


# ---------- the order of the files and the parts ----------


def test_natural_order():
    names = ["Глава 10.doc", "Глава 2.doc", "Глава 1.doc"]
    assert sorted(names, key=natural_key) == ["Глава 1.doc", "Глава 2.doc", "Глава 10.doc"]


def test_walk_in_natural_order(tmp_path):
    for n in ("Глава 10.doc", "Глава 2.doc", "Глава 1.doc"):
        (tmp_path / n).write_bytes(b"x")
    assert [rel for _, rel in prepare.walk(tmp_path)] == ["Глава 1.doc", "Глава 2.doc", "Глава 10.doc"]


def test_part_order():
    rows = [({"order": 3}, "b/Глава 1.doc", "T0003"), ({}, "b/Глава 10.doc", "T0002"), ({}, "b/Глава 2.doc", "T0004")]
    got = [t for m, rel, t in sorted(rows, key=lambda x: build.part_order(*x))]
    assert got == ["T0003", "T0004", "T0002"]  # a given order first, the rest by name with numbers as numbers
    ordered = sorted([({"order": 2}, "x", "T9"), ({"order": 1}, "y", "T8")], key=lambda x: build.part_order(*x))
    assert [t for *_, t in ordered] == ["T8", "T9"]


def test_part_order_checked():
    meta = {
        "T0001": {"sec": "N", "en": "Book", "title": {"en": "Book", "ru": "Книга"}},
        "T0002": {"part": "T0001", "order": 0},
    }
    errors = meta_schema.check(meta, languages=["ru", "en"])
    assert any("order=0" in e for e in errors)


# ---------- folder books ----------


def test_book_in_a_folder_of_chapters():
    rows = [
        {"tid": "T0001", "rel": "Книга/Введение.doc"},
        {"tid": "T0002", "rel": "Книга/Глава 10.doc"},
        {"tid": "T0003", "rel": "Книга/Глава 2.doc"},
        {"tid": "T0004", "rel": "Книга/Глава 1.doc"},
        {"tid": "T0005", "rel": "Другое/отчёт.pdf"},
    ]
    assert metadraft.book_groups(rows) == [("Книга", "T0004", ["T0001", "T0003", "T0002"])]
    drafts = [{"tid": r["tid"], "title": {"ru": "x"}, "sec": "B"} for r in rows]
    metadraft.group_books(drafts, rows)
    by = {d["tid"]: d for d in drafts}
    assert by["T0004"]["title"] == {"ru": "Книга"} and by["T0004"]["question"]
    assert by["T0003"] == {"tid": "T0003", "part": "T0004", "what": "Глава 2", "order": 3, "draft": True}
    assert by["T0005"]["sec"] == "B"  # a file of another folder stays a document


def test_folder_with_a_contents_file():
    rows = [{"tid": "T0001", "rel": "Книга/Оглавление.doc"}, {"tid": "T0002", "rel": "Книга/Часть первая.doc"}]
    assert metadraft.book_groups(rows) == [("Книга", "T0001", ["T0002"])]
    assert metadraft.book_groups([{"tid": "T1", "rel": "a/x.doc"}, {"tid": "T2", "rel": "a/y.doc"}]) == []


# ---------- drafts during the batch ----------


def _state(tmp_path, rels):
    state = State(tmp_path / "state.sqlite")
    (tmp_path / "md").mkdir()
    for rel in rels:
        t = state.add(rel, 1)
        state.update(t, status="done")
        (tmp_path / "md" / f"{t}.md").write_text(page(1, "СЕПАРАЦИЯ НЕФТИ И ГАЗА\nМосква: Недра, 2005"), encoding="utf-8")
    return state


def test_drafts_appended_per_file(tmp_path):
    state = _state(tmp_path, ["a.pdf", "b.pdf"])
    assert metadraft.write_drafts(tmp_path, state, tids=["T0001"], append=True) == 1
    assert metadraft.write_drafts(tmp_path, state, tids=["T0002"], append=True) == 1
    assert metadraft.write_drafts(tmp_path, state, tids=["T0001"], append=True) == 1  # again: replaced, not doubled
    lines = [json.loads(x) for x in (tmp_path / "meta_draft.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(d["tid"] for d in lines) == ["T0001", "T0002"]
    assert metadraft.write_drafts(tmp_path, state) == 2  # the pass at the end writes the file anew


def test_the_batch_drafts_a_file_as_soon_as_it_is_done(project, monkeypatch):
    from assistant_x.intake import pipeline as intake
    from tests.intake.test_intake_pool import FakePool

    root, cfg = project
    monkeypatch.setenv("AX_FP_CACHE", str(cfg.fingerprints))
    monkeypatch.setattr(intake.Batch, "pool", lambda self: FakePool([]))
    calls, real = [], metadraft.write_drafts

    def spy(work, state, tids=None, **kw):
        calls.append((tids, kw.get("append", False)))
        return real(work, state, tids=tids, **kw)

    monkeypatch.setattr(metadraft, "write_drafts", spy)
    assert intake.main(["--config", str(cfg.path), "run"]) == 0
    per_file = [t for t, append in calls if append]
    assert per_file and all(len(t) == 1 for t in per_file)  # one file at a time, during the batch
    assert calls[-1] == (None, False)  # then the whole file anew


# ---------- standards (audit 7) ----------


def test_a_national_standard_with_an_em_dash():
    md = page(
        1,
        "МЕЖГОСУДАРСТВЕННЫЙ СТАНДАРТ\n\nГОСТ 33000—2014\n\nТРУБЫ БУРИЛЬНЫЕ\nТехнические условия\n\n"
        "Drill pipes. Specifications\n\nИздание официальное",
    )
    d = metadraft.draft(md, "ГОСТ 33000.pdf")
    assert d["designation"]["ru"] == "ГОСТ 33000—2014" and d["year"] == 2014 and d["doc_type"] == "standard"
    assert d["title"]["en"] == "Drill pipes. Specifications"
    assert metadraft.references("по ГОСТ 1234—80 и ISO 10424—2") == [
        {"designation": "ГОСТ 1234—80"},
        {"designation": "ISO 10424—2"},
    ]


def test_a_national_standard_that_adopts_a_foreign_one():
    md = page(
        1,
        "ISO 10424-2:2007\n\nМЕЖГОСУДАРСТВЕННЫЙ СТАНДАРТ\n\nГОСТ 33000-2014\n(ISO 10424-2:2007, NEQ)\n\n"
        "ОБОРУДОВАНИЕ БУРОВОЕ\nЧасть 2",
    )
    d = metadraft.draft(md, "x.pdf")
    assert d["designation"]["ru"] == "ГОСТ 33000-2014"  # the national one, not the foreign one above it
    assert d["adopts"] == ["ISO 10424-2:2007"]
    from assistant_x.core import card as C

    line = {**d, "sec": "N", "title": {"en": "Drilling equipment", "ru": "Оборудование буровое"}, "topics": ["drilling"]}
    line.update(summary="Drilling equipment.", keywords={"en": ["drilling"]}, designation={"en": "GOST 33000-2014"})
    card = meta_schema.card_of(line, "N-00001")
    assert card["doc"]["adopts"] == ["ISO 10424-2:2007"] and not C.validate(card)
    assert "ISO 10424-2:2007" in C.search_text(card)


def test_the_file_name_gives_the_year():
    md = page(1, "НАЦИОНАЛЬНЫЙ СТАНДАРТ\n\nГОСТ Р 51858\n\nНЕФТЬ\nОбщие технические условия")
    assert metadraft.draft(md, "ГОСТ Р 51858-2002.pdf")["designation"]["ru"] == "ГОСТ Р 51858-2002"
    assert metadraft.draft(md, "ГОСТ Р 52000-2005.pdf")["designation"]["ru"] == "ГОСТ Р 51858"  # another number
    assert metadraft.same_number("ГОСТ 33000", "ГОСТ 33000-2014") and not metadraft.same_number("ГОСТ 3300", "ГОСТ 33000")


def test_an_amendment_is_no_version_of_its_base():
    from assistant_x.intake import versions

    md = page(1, "Изменение № 1 ГОСТ 33000-2014 Трубы бурильные. Технические условия\n\nДата введения 2016-01-01")
    d = metadraft.draft(md, "Изм 1.pdf")
    assert d["doc_type"] == "standard" and d["amends"] == "ГОСТ 33000-2014" and "designation" not in d
    assert d["title"]["ru"].startswith("Изменение № 1")
    docs = [("N-00001", "Трубы бурильные. Технические условия", "ГОСТ 33000-2014")]
    assert versions.find(d.get("code_hint"), " ".join(d["title"].values()), docs) is None


def test_contents_without_service_lines_and_repeats():
    assert not metadraft.heading_ok("Дата введения 2016-01-01")
    assert not metadraft.heading_ok("Введен в действие впервые")
    pages = [
        (1, "# 1 Область применения\n\n# 1 Область применения\n\n# 2 Нормативные ссылки"),
        (2, "# 3 Термины и определения"),
    ]
    toc, _ = metadraft.contents(pages)
    assert [t["title"] for t in toc].count("1 Область применения") <= 1
