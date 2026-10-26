# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The JSON cards (core/card.py, schemas/card-1.json): the example of the schema is valid, every limit and rule is
enforced, a card is written the same way every time and reads back unchanged."""

import copy, json

import pytest

from assistant_x.core import card as C

RU = ("en", "ru")


def example():
    """The example card of the plan of the cards (a Russian standard)."""
    return {
        "code": "N-00012",
        "doc": {
            "authors": [],
            "designation": {"en": "GOST 1510-84", "ru": "ГОСТ 1510-84"},
            "edition": "",
            "keywords": {
                "en": ["tank", "filling", "vapor losses", "rail tank car", "storage period"],
                "ru": ["резервуар", "налив", "потери от испарения", "железнодорожная цистерна", "срок хранения"],
            },
            "lang": ["ru"],
            "other_versions": [],
            "page_offset": {"checked": False, "value": 0},
            "publisher": "Izdatelstvo standartov",
            "questions": ["How long may petroleum products be stored in tanks?"],
            "references": [{"designation": "GOST 2517-2012"}],
            "scope": "Rules for marking, packaging, transport and storage of crude oil and petroleum products.",
            "summary": "Marking, packaging, transport and storage of crude oil and petroleum products: containers, tanks, "
            "rail tank cars, storage periods.",
            "tables": [{"label": "Table 3", "pdf_page": 18, "title": {"en": "Storage periods", "ru": "Сроки хранения"}}],
            "terms": [{"name": {"en": "vertical steel tank", "ru": "РВС"}, "expansion": "резервуар вертикальный стальной"}],
            "title": {
                "en": "Petroleum and petroleum products. Marking, packaging, transportation and storage",
                "ru": "Нефть и нефтепродукты. Маркировка, упаковка, транспортирование и хранение",
            },
            "toc": [{"level": 1, "pdf_from": 14, "title": {"en": "Storage", "ru": "Хранение"}}],
            "topics": ["storage", "transportation", "marking", "packaging"],
            "year": 1984,
        },
        "doc_type": "standard",
        "file": {
            "format": {"kind": "pdf_scan", "ocr_pages": 48, "ocr_score": 0.94, "pages": 48},
            "hidden_text": [],
            "issues": [],
            "library": "library/01_Standards/N-00012_GOST-1510-84.pdf",
            "parts": [],
            "pdf_copy": "",
            "sha256": "ab" * 32,
            "size": 2311040,
            "source_name": "ГОСТ 1510-84.pdf",
            "text": "index/texts/N-00012.md",
        },
        "intake": {"batch": "2026-10-25_01", "date": "2026-10-25", "personal": False},
        "schema": 1,
        "section": "N",
    }


def serial():
    c = example()
    c.update(code="J-00003", section="J", doc_type="serial_issue")
    c["doc"].pop("designation")
    c["doc"].update(
        serial={"name": {"en": "Oil Industry", "ru": "Нефтяное хозяйство"}, "issn": "0028-2448", "volume": 12, "number": 3},
        units=[
            {
                "kind": "article",
                "title": {"en": "Separator sizing", "ru": "Расчёт сепараторов"},
                "authors": ["Ivanov I. I."],
                "pdf_from": 5,
                "summary": "Gas velocity limits in separators.",
            },
            {"kind": "article", "title": {"en": "Tank losses", "ru": "Потери в резервуарах"}, "pdf_from": 11},
        ],
    )
    return c


def test_example_is_valid():
    assert C.validate(example(), RU) == []
    assert C.validate(serial(), RU) == []
    assert "standard" in C.doc_types() and "serial_issue" in C.doc_types()


@pytest.mark.parametrize(
    "path, value, what",
    [
        (("doc", "summary"), "x" * 801, "summary"),
        (("doc", "scope"), "x" * 301, "scope"),
        (("doc", "questions"), ["q?"] * 6, "questions"),
        (("doc", "keywords", "en"), [f"w{i}" for i in range(31)], "keywords"),
        (("doc", "topics"), [], "topics"),
        (("doc", "topics"), [f"t{i}" for i in range(9)], "topics"),
        (("doc", "terms"), [{"name": {"en": f"t{i}", "ru": f"т{i}"}} for i in range(41)], "terms"),
        (("doc", "toc"), [{"level": 1, "pdf_from": 1, "title": {"en": "a", "ru": "а"}}] * 301, "toc"),
        (("doc", "tables"), [{"label": "Table 1", "pdf_page": 1}] * 101, "tables"),
        (("doc", "topics"), ["Storage"], "topics"),
        (("doc_type",), "novel", "doc_type"),
        (("doc", "year"), "1984", "year"),
        (("file", "format", "kind"), "scan", "format"),
        (("file", "sha256"), "xyz", "sha256"),
    ],
)
def test_limits(path, value, what):
    c = example()
    target = c
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    errors = C.validate(c, RU)
    assert errors and any(what in e for e in errors), errors


def test_unknown_field_and_missing_block():
    c = example()
    c["doc"]["status"] = "in force"  # no validity status in a card
    assert any("status" in e for e in C.validate(c, RU))
    c = example()
    del c["file"]
    assert any("file" in e for e in C.validate(c, RU))


def test_languages():
    c = example()
    del c["doc"]["title"]["ru"]
    assert C.validate(c, ("en",)) == []  # the general profile needs English only
    assert any(e.startswith("doc/title: no text in ru") for e in C.validate(c, RU))
    c = example()
    del c["doc"]["terms"][0]["name"]["en"]  # English is always required, by the schema itself
    assert any("terms/0/name" in e for e in C.validate(c, ("en",)))
    c = example()
    c["doc"]["toc"][0]["title"] = {"en": "Storage"}
    assert any("toc/0/title: no text in ru" in e for e in C.validate(c, RU))
    c = serial()
    del c["doc"]["units"][1]["title"]["ru"]
    assert any("units/1/title" in e for e in C.validate(c, RU))
    c["doc"]["serial"]["name"] = {"ru": "Нефтяное хозяйство"}
    assert any("serial/name" in e for e in C.validate(c, RU))


@pytest.mark.parametrize(
    "code, section, what",
    [
        ("N-0012", "N", "code"),  # four digits: the old codes
        ("N-000012", "N", "code"),
        ("n-00012", "N", "code"),
        ("N-00012-02", "N", "code"),  # a part has no card of its own
        ("L-00012", "N", "disagree"),
    ],
)
def test_bad_codes(code, section, what):
    c = example()
    c.update(code=code, section=section)
    errors = C.validate(c, RU)
    assert errors and any(what in e for e in errors), errors


def test_sections_and_topics_of_the_profile():
    c = example()
    assert C.validate(c, RU, sections=("N", "L")) == []
    assert any("not a shelf of the library" in e for e in C.validate(c, RU, sections=("R", "L")))
    assert C.validate(c, RU, topics={"storage", "transportation", "marking", "packaging"}) == []
    assert any("topics of the profile" in e for e in C.validate(c, RU, topics={"storage"}))


def test_parts():
    c = example()
    c["file"]["parts"] = [
        {
            "code": "N-00012-02",
            "library": "library/01_Standards/N-00012/N-00012-02_Scan.pdf",
            "format": {"kind": "pdf_scan", "pages": 3},
            "text": "index/texts/N-00012-02.md",
        }
    ]
    assert C.validate(c, RU) == []
    c["file"]["parts"].append(dict(c["file"]["parts"][0]))
    assert any("twice" in e for e in C.validate(c, RU))
    c["file"]["parts"] = [dict(c["file"]["parts"][0], code="N-00013-02")]
    assert any("is not of N-00012" in e for e in C.validate(c, RU))


@pytest.mark.parametrize(
    "where,value",
    [
        ("library", "../../VICTIM.txt"),
        ("library", "library/../../x.pdf"),
        ("library", "C:/library/x.pdf"),
        ("library", "/library/x.pdf"),
        ("library", "library\\x.pdf"),
        ("library", "library/a:stream.pdf"),
        ("library", "index/texts/N-00012.md"),
        ("pdf_copy", "../x.pdf"),
        ("pdf_copy", "library/./x.pdf"),
        ("text", "library/x.md"),
        ("text", "index/texts/../cards/x.md"),
        ("text", "index/texts//x.md"),
    ],
)
def test_paths_stay_in_the_workspace(where, value):
    c = example()
    c["file"][where] = value
    assert any(f"file/{where}" in e for e in C.validate(c, RU)), value
    c = example()
    c["file"]["parts"] = [
        {
            "code": "N-00012-02",
            "library": "library/01_Standards/N-00012/N-00012-02_Scan.pdf",
            "format": {"kind": "pdf_scan", "pages": 3},
            "text": "index/texts/N-00012-02.md",
            where: value,
        }
    ]
    assert any(f"file/parts/0/{where}" in e for e in C.validate(c, RU)), value


def test_codes():
    assert C.new_code("N", 12) == "N-00012" and C.part_code("N-00012", 2) == "N-00012-02"
    assert C.main_code("E-00006-02") == "E-00006" and C.main_code("E-00006") == "E-00006"
    rx = C.code_rx("NL")
    assert rx.match("N-00012") and rx.match("L-00001-03")["part"] == "03"
    assert not rx.match("R-00001") and not rx.match("N-0001")
    with pytest.raises(C.CardError):
        C.new_code("N", 100000)


def test_dump_load_round_trip(tmp_path):
    c = example()
    p = tmp_path / "N-00012.json"
    C.dump(c, p)
    raw = p.read_bytes()
    assert raw.endswith(b"}\n") and b"\r" not in raw
    assert "ГОСТ 1510-84" in raw.decode("utf-8")  # letters as they are, not \u escapes
    assert raw.decode("utf-8") == json.dumps(c, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    assert C.load(p) == c
    sha = C.sha(p)
    C.dump(copy.deepcopy(c), p)
    assert C.sha(p) == sha  # the same card writes the same bytes
    (tmp_path / "_README.md").write_text("notes", encoding="utf-8")
    (tmp_path / "_draft.json").write_text("{}", encoding="utf-8")
    assert list(C.paths(tmp_path)) == ["N-00012"]


def test_migrate():
    assert C.migrate(example()) == example()
    with pytest.raises(C.CardError):
        C.migrate(dict(example(), schema=99))


def test_load_errors(tmp_path):
    p = tmp_path / "N-00001.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(C.CardError):
        C.load(p)


def test_complete():
    c = example()
    for k in ("toc", "tables", "edition", "designation"):
        del c["doc"][k]
    full = C.complete(c)
    assert full["doc"]["toc"] == [] and full["doc"]["edition"] == "" and "designation" not in full["doc"]
    assert C.validate(full, RU) == []


def test_brief_and_search_text():
    c = example()
    b = C.brief(c)
    assert b.startswith("N-00012 · Petroleum and petroleum products")
    assert "ГОСТ 1510-84" in b and "Table 3 «Storage periods / Сроки хранения» — PDF 18" in b
    assert "library/" not in b and "Хранение — PDF 14" not in b  # no file block, no contents by default
    assert "Contents: 1 entries" in b
    toc = C.brief(c, ["toc"])
    assert "Storage / Хранение — PDF 14" in toc and "Summary" not in toc
    assert "library/01_Standards" in C.brief(c, ["file"])
    s = C.search_text(c)
    for w in (
        "ГОСТ 1510-84",
        "Petroleum and petroleum",
        "Нефть и нефтепродукты",
        "потери от испарения",
        "РВС",
        "How long may",
        "storage, transportation",
    ):
        assert w in s
    assert "pdf_scan" not in s and "library" not in s
    u = serial()["doc"]["units"][0]
    assert C.unit_text(u) == "Separator sizing / Расчёт сепараторов\nIvanov I. I.\nGas velocity limits in separators."
    assert "PDF 5: Separator sizing" in C.brief(serial())


def test_format_line_and_ocr_share():
    assert C.format_line({"kind": "pdf_scan", "pages": 48}) == "PDF scan (OCR, errors possible), 48 pages"
    assert C.format_line({"kind": "pdf_mixed", "pages": 40, "ocr_pages": 12}).startswith("PDF with text, some pages")
    assert C.ocr_share({"kind": "pdf_mixed", "pages": 40, "ocr_pages": 12}) == 0.3
    assert C.ocr_share({"kind": "pdf_text", "pages": 4}) == 0.0 and C.ocr_share({"kind": "other"}) is None


def test_search_texts_a_fragment_per_language_and_the_questions():
    card = {
        "code": "N-00007",
        "doc": {
            "title": {"en": "Oil separators", "ru": "Сепараторы нефти"},
            "designation": {"ru": "ГОСТ Р 7-2020"},
            "scope": "Field separators.",
            "summary": "Sizing and testing.",
            "keywords": {"en": ["separator"], "ru": ["сепаратор"]},
            "terms": [{"name": {"en": "GOR", "ru": "ГФ"}, "expansion": "газовый фактор"}],
            "questions": ["How is a separator sized?", "  "],
            "topics": ["oil_treatment"],
        },
    }
    out = C.search_texts(card)
    assert [(k, lang) for k, lang, _ in out] == [("card", "en"), ("card", "ru"), ("card_q", "")]
    en, ru, q = (t for _, _, t in out)
    assert en.splitlines() == [
        "ГОСТ Р 7-2020",
        "Oil separators",
        "Field separators.",
        "Sizing and testing.",
        "separator",
        "GOR — газовый фактор",
    ]  # a designation in no English: the one there is
    assert ru.splitlines()[:2] == ["ГОСТ Р 7-2020", "Сепараторы нефти"] and "ГФ — газовый фактор" in ru
    assert q.splitlines() == ["How is a separator sized?", "oil treatment"]
    assert C.card_langs({}) == ["en"] and C.search_texts({"doc": {}}) == []
    assert "Oil separators / Сепараторы нефти" in C.search_text(card)  # the joined text stays for its callers
