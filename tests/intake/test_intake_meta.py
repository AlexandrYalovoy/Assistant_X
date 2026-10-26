# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""meta_schema.py (checks of meta.jsonl) and metadraft.py (draft from the first pages)."""

import datetime, json

import pytest

from assistant_x.intake import meta_schema
from assistant_x.intake import metadraft
from tests.intake.intake_fixtures import doc_line

GOOD = {
    "T0001": doc_line("T0001", "N", "Сепараторы", "Separators", designation={"en": "GOST R 1-2020", "ru": "ГОСТ Р 1-2020"}),
    "T0002": {"tid": "T0002", "part": "T0001", "what": "Scan"},
    "T0003": {"tid": "T0003", "dupof": "L-00012", "why": "another scan"},
    "T0004": {"tid": "T0004", "drop": "administrative pages only"},
    "T0005": doc_line("T0005", "L", "Книга", "Book", year=1984),
}
RULES = {"sections": ["N", "L", "P", "E", "R", "J", "X"], "languages": ["en", "ru"]}  # the shelves, Russian documents


def errors(meta, tids=None):
    return meta_schema.check(meta, tids, **RULES)


def test_good_meta():
    assert errors(GOOD, set(GOOD)) == []


@pytest.mark.parametrize(
    "change, expect",
    [
        ({"T0001": {"tid": "T0001", "title": {"en": "x"}, "en": "X"}}, "exactly one"),
        ({"T0001": {**GOOD["T0001"], "sec": "Q"}}, "section"),
        ({"T0001": {**GOOD["T0001"], "title": {"en": "Separators"}}}, "doc/title: no text in ru"),
        ({"T0001": {**GOOD["T0001"], "title": "Сепараторы"}}, "doc/title"),  # a map of languages, not a string
        ({"T0001": {**GOOD["T0001"], "en": ""}}, "English title"),
        ({"T0001": {**GOOD["T0001"], "doc_type": "novel"}}, "doc_type"),
        ({"T0001": {**GOOD["T0001"], "summary": "x" * 801}}, "summary"),
        ({"T0001": {**GOOD["T0001"], "keywords": {"ru": ["тест"]}}}, "keywords"),
        ({"T0005": {**GOOD["T0005"], "year": 1899}}, "year"),
        ({"T0005": {**GOOD["T0005"], "year": datetime.date.today().year + 2}}, "year"),
        ({"T0005": {**GOOD["T0005"], "year": "1984"}}, "year"),
        ({"T0001": {**GOOD["T0001"], "replaces": "N1"}}, "replaces: a code"),
        ({"T0001": {**GOOD["T0001"], "replaces": "N-0001"}}, "replaces: a code"),  # four digits: an old code
        ({"T0001": {**GOOD["T0001"], "replaces": "L-00001"}}, "keeps the section"),
        ({"T0001": {**GOOD["T0001"], "replaces": "N-00001", "other_version": "N-00002"}}, "together"),
        ({"T0001": {**GOOD["T0001"], "issues": [{"what": "poor scan"}]}}, "issues/0"),
        ({"T0001": {**GOOD["T0001"], "kw": "old field"}}, "unknown fields kw"),
        ({"T0002": {"tid": "T0002", "part": "T0099"}}, "part refers to T0099"),
        ({"T0002": {"tid": "T0002", "part": "T0004"}}, "not a document"),
        ({"T0003": {"tid": "T0003", "dupof": "something"}}, "dupof"),
        ({"T0001": {**GOOD["T0001"], "sec": "N", "drop": "x"}}, "exactly one"),
    ],
)
def test_bad_meta(change, expect):
    meta = {**GOOD, **change}
    assert any(expect in e for e in errors(meta, set(GOOD))), errors(meta, set(GOOD))


def test_year_next_is_allowed_and_issues():
    meta = {
        "T0001": {
            **GOOD["T0001"],
            "replaces": "N-00001",
            "issues": [{"what": "a poor scan", "need": "a better one", "priority": "high"}],
        },
        "T0005": {**GOOD["T0005"], "year": datetime.date.today().year + 1},
    }
    assert errors(meta) == []


def test_english_documents_only_need_english_cards():
    """The card languages follow the languages the documents are read in: English always."""
    line = {**GOOD["T0005"], "title": {"en": "Book"}, "keywords": {"en": ["test"]}}
    assert meta_schema.check({"T0005": line}, sections=RULES["sections"], languages=["en"]) == []
    assert any("no text in ru" in e for e in meta_schema.check({"T0005": line}, **RULES))


def test_unknown_tid_and_bad_lines(tmp_path):
    assert any("no such file in the batch" in e for e in errors({"T0007": {**GOOD["T0005"], "tid": "T0007"}}, {"T0001"}))
    p = tmp_path / "meta.jsonl"
    p.write_text(
        '{"tid": "T0001", "sec": "L", "en": "A"}\nnot json\n{"sec": "N"}\n{"tid": "T0001", "year": 2001}\n', encoding="utf-8"
    )
    meta, errs = meta_schema.load(p)
    assert meta["T0001"]["year"] == 2001 and meta["T0001"]["sec"] == "L"  # lines of one tid merge
    assert len(errs) == 2


PAGES = {
    "gost": (
        "=== page 1 ===\n\nФЕДЕРАЛЬНОЕ АГЕНТСТВО ПО ТЕХНИЧЕСКОМУ РЕГУЛИРОВАНИЮ\n\nНАЦИОНАЛЬНЫЙ СТАНДАРТ\n\n"
        "ГОСТ Р 58367­2019\n\nОБУСТРОЙСТВО МЕСТОРОЖДЕНИЙ НЕФТИ НА СУШЕ Технологическое проектирование\n\n"
        "Москва Стандартинформ 2019\n\n=== page 2 ===\n\nВзамен ГОСТ Р 12345-2010\n\n# 1 Область применения\n",
        {
            "sec": "N",
            "doc_type": "standard",
            "code_hint": "ГОСТ Р 58367-2019",
            "au": "GOST-R-58367-2019",
            "year": 2019,
            "publisher": "Стандартинформ",
            "lang": ["ru"],
            "designation": {"ru": "ГОСТ Р 58367-2019", "en": "GOST R 58367-2019"},
            "title": {"ru": "Обустройство месторождений нефти на суше. Технологическое проектирование"},
            "references": [{"designation": "ГОСТ Р 12345-2010"}],
        },
    ),
    "book": (
        "=== page 1 ===\n\nН.В. Кельцев\n\nОСНОВЫ АДСОРБЦИОННОЙ ТЕХНИКИ\n\nИздание 2-е\n\nМ.: Химия, 1984\n\nУДК 66.081\n",
        {
            "sec": "L",
            "doc_type": "book",
            "year": 1984,
            "publisher": "М.: Химия, 1984",
            "title": {"ru": "Основы адсорбционной техники"},
        },
    ),
    "api": (
        "=== page 1 ===\n\n# Recommended Practice for Design of Offshore Piping\n\nAPI RP 14E\nFifth Edition, October 1991\n"
        "American Petroleum Institute\n",
        {
            "sec": "N",
            "code_hint": "API RP 14E",
            "year": 1991,
            "publisher": "American Petroleum Institute",
            "lang": ["en"],
            "designation": {"en": "API RP 14E"},
            "title": {"en": "Recommended Practice for Design of Offshore Piping"},
        },
    ),
    "sp": (
        "=== page 1 ===\n\nСП 231.1311500.2015\n\nОБУСТРОЙСТВО НЕФТЯНЫХ И ГАЗОВЫХ МЕСТОРОЖДЕНИЙ\n",
        {"sec": "N", "code_hint": "СП 231.1311500.2015", "au": "SP-231-1311500-2015", "year": 2015},
    ),
    "passport": (
        "=== page 1 ===\n\nНАСОС ЦЕНТРОБЕЖНЫЙ ЦНС 60-330\n\nПаспорт и руководство по эксплуатации\n\n"
        "ООО «Завод насосов» 2015\n",
        {"sec": "E", "doc_type": "datasheet", "year": 2015, "publisher": "ООО «Завод насосов»"},
    ),
    "regulation": (
        "=== page 1 ===\n\nТЕХНОЛОГИЧЕСКИЙ РЕГЛАМЕНТ установки подготовки нефти УПН-1\n\nПАО «Пример» 2021\n",
        {"sec": "R", "doc_type": "regulation", "year": 2021},
    ),
    "journal": (
        "=== page 1 ===\n\nНаучно-технический журнал\n\n# Содержание\n\nРасчёт газовых сепараторов ........ 2\n\n"
        "Коррозия промысловых трубопроводов ........ 3\n\nПотери нефти при хранении ........ 3\n\n"
        "=== page 2 ===\n\n# Расчёт газовых сепараторов\n\nТекст статьи о расчёте газовых сепараторов.\n\n"
        "=== page 3 ===\n\n# Коррозия промысловых трубопроводов\n\nТекст статьи о коррозии.\n\n"
        "# Потери нефти при хранении\n\nТекст статьи о потерях.\n",
        {"sec": "J", "doc_type": "serial_issue"},
    ),
}


@pytest.mark.parametrize("kind", sorted(PAGES))
def test_metadraft(kind):
    md, expect = PAGES[kind]
    d = metadraft.draft(md, f"Папка/{kind}.pdf", {"profile": "oil-gas-ru"})
    for k, v in expect.items():
        assert d.get(k) == v, (k, d)
    assert d["draft"] is True and "st" not in d and "out" not in d
    # what Claude adds to a draft: the English title, the summary, the topics, the keywords
    lg = (d.get("lang") or ["en"])[0]
    line = {
        **d,
        "tid": "T0001",
        "en": "Title",
        "title": {**d["title"], "en": "Title", "ru": d["title"].get("ru", "Заглавие")},
        "summary": "A summary.",
        "topics": ["test"],
        "keywords": {"en": ["test"], "ru": ["тест"]},
    }
    for key in ("toc", "units"):
        for x in line.get(key, []):
            x["title"] = {"en": "Entry", "ru": x["title"].get("ru", "Раздел")}
    if "designation" in line:
        line["designation"] = {"en": line["designation"].get("en", "X"), "ru": line["designation"].get(lg, "X")}
    assert meta_schema.check({"T0001": line}, **RULES) == []


def test_metadraft_supersedes_hint_and_file_name():
    d = metadraft.draft(PAGES["gost"][0])
    assert d["supersedes"] == "ГОСТ Р 12345-2010"
    d = metadraft.draft(
        "=== page 1 ===\n\nНекий текст без обозначения\n",
        "НД/СТО Пример 2-3.5-051-2006 Нормы.pdf",
        {"profile": "oil-gas-ru"},
    )
    assert d["code_hint"].startswith("СТО Пример 2-3.5-051-2006") and d["sec"] == "N"
    json.dumps(d, ensure_ascii=False)


def test_draft_contents_tables_and_units():
    """The draft of the whole text: the contents with pages, the tables, the articles of a journal issue."""
    d = metadraft.draft(PAGES["journal"][0], "j.pdf", {"profile": "oil-gas-ru"})
    assert [(u["pdf_from"], u["title"]["ru"]) for u in d["units"]] == [
        (2, "Расчёт газовых сепараторов"),
        (3, "Коррозия промысловых трубопроводов"),
        (3, "Потери нефти при хранении"),
    ]
    md = (
        "=== page 1 ===\n\n# 1 Общие положения\n\nТекст.\n\n=== page 2 ===\n\n# 2 Расчёт\n\nТаблица 1 — Дебит\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n=== page 3 ===\n\n# 3 Замер\n\nТаблица 2 — Замер\n\n| a |\n|---|\n| 1 |\n"
    )
    d = metadraft.draft(md, "x.pdf", {"profile": "oil-gas-ru"})
    assert [(t["level"], t["pdf_from"], t["title"]["ru"]) for t in d["toc"]] == [
        (1, 1, "1 Общие положения"),
        (1, 2, "2 Расчёт"),
        (1, 3, "3 Замер"),
    ]
    assert d["tables"] == [{"label": "Table 1", "pdf_page": 2}, {"label": "Table 2", "pdf_page": 3}]


def test_draft_shelf_is_the_same_in_every_profile():
    """The genre gives the shelf, the same in every profile: a standard on N, a journal issue on J."""
    for profile in ({"profile": "oil-gas-ru"}, {"profile": "general"}):
        assert metadraft.draft(PAGES["gost"][0], "", profile)["sec"] == "N"
        assert metadraft.draft(PAGES["journal"][0], "", profile)["sec"] == "J"
    assert metadraft.shelf_of("novel_type") == "X"


@pytest.mark.parametrize(
    "page, want",
    [
        # the first words in capitals, then the rest of the title
        ("СЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ Общие технические требования", "Сепараторы нефтегазовые. Общие технические требования"),
        # the first word is not all capitals («ГОСТы»): metadraft used to fail on it, the line stays as it is
        ("ГОСТы на трубы стальные бесшовные для нефтепроводов", "ГОСТы на трубы стальные бесшовные для нефтепроводов"),
        # a Markdown heading wins over the capitals rule
        ("# Руководство по эксплуатации сепараторов\nСЕПАРАТОРЫ НГС ТИП 1", "Руководство по эксплуатации сепараторов"),
    ],
)
def test_title_forms(page, want):
    assert metadraft.title_of([page]) == want


def test_picture_without_text_is_dropped_but_a_drawing_is_not():
    photo = "=== page 1 ===\n\nООО Ромашка 2019\n"
    assert metadraft.draft(photo, "Фото/IMG_0012.jpg")["drop"].startswith("a picture without text")
    drawing = "=== page 1 ===\n\nСхема узла Масштаб 1:50 Лист 1 Листов 3 Разраб. Иванов\n"
    assert "drop" not in metadraft.draft(drawing, "Чертежи/узел.png")
    assert "drop" not in metadraft.draft(photo, "Документы/письмо.pdf")  # only pictures


def test_two_text_layers_gost_title():
    """Two text layers of a ГОСТ from the registry site: spaced capitals, a drop cap, every phrase twice."""
    assert metadraft.tidy("М МЕЖГОСУДАРСТВЕННЫЙ Е Ж Г О С У Д А Р С Т В Е Н Н Ы Й") == "МЕЖГОСУДАРСТВЕННЫЙ"
    assert metadraft.tidy("ОБЩИЕ ОБЩИЕ ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ") == "ОБЩИЕ ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ"
    assert metadraft.tidy("Кронблоки, кронблоки, блоки талевые, блоки талевые, крюки") == "Кронблоки, блоки талевые, крюки"
    page = (
        "ГОСТ 15880-83 ГОСТ 15880—83\n\nМ МЕЖГОСУДАРСТВЕННЫЙ Е Ж Г О С У Д А Р С Т В Е Н Н Ы Й\n\nС СТАНДАРТ Т А Н Д А Р Т\n\n"
        "11—98БЗ\n\n# ЭЛЕКТРОБУРЫ ЭЛЕКТРОБУРЫ\n\nОБЩИЕ ОБЩИЕ ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ\n\n"
        "Издание официальное Издание официальное\n"
    )
    d = metadraft.draft("=== page 1 ===\n" + page)
    assert d["title"] == {
        "ru": "Электробуры. Общие технические требования",
        "en": "Electric Drills General Technical Requirements",
    }
    assert d["en"] == "Electric-Drills-General-Technical-Requirements" and d["designation"]["ru"] == "ГОСТ 15880-83"
    assert metadraft.en_title("Долота шарошечные. Конструкция") == ""  # an unknown word: no guess
