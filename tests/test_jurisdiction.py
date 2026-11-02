# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdiction of a document (core/jurisdiction.py): by its designation (the national designations of
Kazakhstan before the Russian ones that share their letters, the acts of the Eurasian union, interstate GOST, ISO and
IEC apart from the US bodies), by the names of a state in a normative document without a designation, a doubt left
empty; the schema field, the draft of the intake, the backfill of the cards and the jurisdictions filter of the
search."""

import json

import pytest

from assistant_x.core import card as C
from assistant_x.core import jurisdiction as J


@pytest.mark.parametrize(
    "designation, value",
    [
        ("СН РК 3.05-01-2013", "KZ"),
        ("СП РК 3.05-101-2013", "KZ"),
        ("СП РК EN 1993-4-3:2007/2011", "KZ"),
        ("НП к СП РК EN 1990:2002+A1:2005/2011", "KZ"),
        ("СТ РК 4006-2025", "KZ"),
        ("ТР ТС 032/2013", "EAEU"),
        ("ТР ЕАЭС 049/2020", "EAEU"),
        ("ГОСТ 1510-84", "CIS"),
        ("ГОСТ ISO 9001-2011", "CIS"),
        ("ГОСТ Р 51858-2002", "RU"),
        ("ГОСТ Р ИСО 10424-2-2011", "RU"),
        ("СП 4.13130.2013", "RU"),
        ("СНиП 2.04.05-91", "RU"),
        ("Р Газ 9.3-020-2012", "RU"),
        ("116-ФЗ", "RU"),
        ("ISO 9001:2015", "INT"),
        ("IEC 60079-0:2017", "INT"),
        ("IEC/IEEE 80005-1", "INT"),
        ("API RP 14C", "US"),
        ("ASME B31.3-2020", "US"),
        ("ANSI/ISA-12.12.01-2015", "US"),
        ("NFPA 30", "US"),
        ("EN 13480-3:2017", "EU"),
        ("BS 7910:2019", "GB"),
    ],
)
def test_by_designation(designation, value):
    assert J.detect({"designation": {"ru": designation}}, "standard") == (value, "designation")


def test_a_dual_designation_and_an_amendment():
    """Each of "A / B" is read; an amendment goes by the standard it amends."""
    assert J.detect({"designation": {"en": "Amendment No. 1 to GOST 4666-2015", "ru": "Изменение № 1 к ГОСТ 4666-2015"}})[0] == "CIS"
    assert J.detect({"designation": {"ru": "Поправка к ГОСТ Р 51858-2002"}})[0] == "RU"
    assert J.detect({"designation": {"ru": "СТ РК ISO 9001-2016 / ISO 9001:2015"}})[0] == "KZ"


def test_by_words_of_a_normative_document():
    """No designation: the name of the state in the title, the publisher or the source name; then in the text."""
    kz = {"title": {"ru": "Об утверждении Правил устройства электроустановок"}, "publisher": "Министерство юстиции Республики Казахстан"}
    assert J.detect(kz, "regulation") == ("KZ", "words")
    adilet = {"title": {"ru": "Правила пожарной безопасности"}}
    assert J.detect(adilet, "regulation", text="Источник: ИПС «Әділет» (adilet.zan.kz)") == ("KZ", "text")
    union = {"title": {"ru": "О принятии технического регламента Таможенного союза «О безопасности машин и оборудования»"}}
    assert J.detect(union, "law") == ("EAEU", "designation")  # the title of the act names the union
    both = {"title": {"ru": "Решение Евразийской экономической комиссии"}, "publisher": "ИПС «Әділет»"}
    assert J.detect(both, "regulation")[0] == "EAEU"  # an act of the union as Kazakhstan publishes it
    assert J.detect({"title": {"en": "Recommended practice"}, "publisher": "American Petroleum Institute"}, "standard") == ("US", "words")
    assert J.detect({"title": {"ru": "Методика"}, "publisher": "ПАО «Нефтяная компания»"}, "guideline") == ("RU", "words")


def test_a_doubt_is_left_empty():
    """Two states named, or none: unsure, no value; a book gets a value only by a designation."""
    two = {"title": {"ru": "Сравнение норм Российской Федерации и Республики Казахстан"}}
    assert J.detect(two, "guideline") == ("", "unsure")
    assert J.detect({"title": {"ru": "Методика расчета"}}, "guideline") == ("", "unsure")
    assert J.detect({"title": {"ru": "Нефтяные месторождения Казахстана"}}, "book") == ("", "")
    assert J.detect({"designation": {"en": "DEP 32.80.10.10-Gen."}}, "standard") == ("", "unsure")


def test_the_schema_field():
    good = C.complete({"schema": 1, "code": "N-00001", "section": "N", "doc_type": "standard",
                       "doc": {"title": {"en": "T", "ru": "Т"}, "summary": "s", "jurisdiction": "KZ"}})
    assert not [e for e in C.validate(good, ("en",)) if "jurisdiction" in e]
    for bad in ("kz", "KAZ", "EAU", ""):
        card = {**good, "doc": {**good["doc"], "jurisdiction": bad}}
        assert [e for e in C.validate(card, ("en",)) if "jurisdiction" in e], bad
    assert "Jurisdiction: KZ" in C.brief(good)


def test_the_draft_of_the_intake_has_it():
    from assistant_x.intake import metadraft

    md = "<!-- page 1 -->\nСТРОИТЕЛЬНЫЕ НОРМЫ РЕСПУБЛИКИ КАЗАХСТАН\n\nСН РК 3.05-01-2013\n\nМАГИСТРАЛЬНЫЕ ТРУБОПРОВОДЫ\n"
    d = metadraft.draft(md, "СН РК 3.05-01-2013 Магистральные трубопроводы.pdf")
    assert d.get("jurisdiction") == "KZ"


def test_backfill(tmp_path):
    """The cards without a value get one (backed up first with write); a doubt stays empty and is listed."""
    cards, backup = tmp_path / "cards", tmp_path / "backup"
    cards.mkdir()
    rows = {
        "N-00001": ("standard", {"designation": {"ru": "СН РК 3.05-01-2013"}}),
        "N-00002": ("standard", {"designation": {"ru": "ГОСТ Р 51858-2002"}}),
        "N-00003": ("guideline", {}),
        "L-00001": ("book", {}),
        "N-00004": ("standard", {"designation": {"ru": "ГОСТ Р 1-2000"}, "jurisdiction": "RU"}),
    }
    for code, (dt, doc) in rows.items():
        c = {"schema": 1, "code": code, "section": code[0], "doc_type": dt,
             "doc": {"title": {"en": "T", "ru": "Т"}, **doc}, "file": {"source_name": f"{code}.pdf"}}
        (cards / f"{code}.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    res = J.backfill(cards)
    assert res["counts"] == {"KZ": 1, "RU": 2, "(none)": 2} and res["unsure"] == ["N-00003"] and res["kept"] == 1
    assert "jurisdiction" not in json.loads((cards / "N-00001.json").read_text(encoding="utf-8"))["doc"]  # a dry run
    J.backfill(cards, write=True, backup=backup)
    assert json.loads((cards / "N-00001.json").read_text(encoding="utf-8"))["doc"]["jurisdiction"] == "KZ"
    assert sorted(p.name for p in backup.iterdir()) == ["N-00001.json", "N-00002.json"]
    assert "jurisdiction" not in json.loads((backup / "N-00001.json").read_text(encoding="utf-8"))["doc"]

