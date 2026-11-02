# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdictions in the answers (search/jurisdiction.py): the Russian, EAEU, Kazakh and international documents
answer, the American standards come after them as a supplement and never take their places; a question naming a
jurisdiction puts its documents first; the card field wins over the designation."""

from assistant_x.search import jurisdiction as J


def hit(code, designation, **kw):
    return dict(code=code, designation=designation, title=designation, **kw)


def test_the_designation_decides_and_the_card_field_wins():
    j = J.load("oil-gas-ru")
    assert j.of(hit("N-1", "API RP 14E")) == "US"
    assert j.of(hit("N-2", "GOST R 58367-2019 / ГОСТ Р 58367-2019")) == "RU"
    assert j.of(hit("N-3", "ГОСТ 34068-2017")) == "CIS" and j.of(hit("N-7", "ТР ТС 032/2013")) == "EAEU"
    assert {"RU", "CIS", "EAEU", "KZ", "INT"} <= j.home and "CIS" not in j.extra  # interstate GOST: primary
    assert j.of(hit("N-4", "СТ РК 1916-2009")) == "KZ" and j.of(hit("N-5", "ISO 13703")) == "INT"
    assert j.of(hit("N-6", "API 6D", jurisdiction="KZ")) == "KZ"
    assert J.load("general") is None  # a profile without the file changes nothing


def test_american_standards_are_a_supplement_after_the_home_answer():
    j = J.load("oil-gas-ru")
    res = [hit("N-1", "API RP 14E"), hit("N-2", "ГОСТ Р 58367-2019"), hit("N-3", "ASME B31.3"),
           hit("N-4", "ТТР-01.02.04-13"), hit("N-5", "API 5L"), hit("N-6", "ISO 13703"), hit("N-7", "РД 39-135-94")]  # fmt: skip
    got = [r["code"] for r in j.arrange(res, "как выбрать диаметр газопровода по скорости газа", 3)]
    assert got == ["N-2", "N-4", "N-6", "N-1", "N-3"]  # the home top 3 intact, two American after it


def test_a_question_naming_a_jurisdiction_puts_it_first():
    j = J.load("oil-gas-ru")
    res = [hit("N-1", "ГОСТ Р 55990-2014"), hit("N-2", "СН РК 3.05-01-2013"), hit("N-3", "API RP 14E")]
    assert [r["code"] for r in j.arrange(res, "что говорят казахстанские нормы о трубопроводах", 3)][0] == "N-2"
    assert [r["code"] for r in j.arrange(res, "требования API к скорости", 3)][0] == "N-3"
    assert [r["code"] for r in j.arrange(res, "что говорят американские нормы о скорости газа", 3)][0] == "N-3"
    assert j.asked("по ASME B31.3 какая толщина стенки") == ["US"]
    assert j.asked("нормы РК по факелам") == ["KZ"] and j.asked("скорость газа") == []


def test_the_card_field_of_the_search_rows_decides(lib):
    """A hit carries the jurisdiction of its card (doc.jurisdiction) when it has one; the designation decides else."""
    import json as _json

    import sqlite3

    j = J.load("oil-gas-ru")
    con = sqlite3.connect(lib.cfg["db"])
    before = con.execute("SELECT card FROM docs WHERE code='N-00001'").fetchone()[0]
    card = _json.loads(before)
    card.setdefault("doc", {})["jurisdiction"] = "KZ"
    try:
        con.execute("UPDATE docs SET card=? WHERE code='N-00001'", (_json.dumps(card, ensure_ascii=False),))
        con.commit()
        hit = next(r for r in lib.search("обводнённости", k=8) if r["code"] == "N-00001")
        assert hit["jurisdiction"] == "KZ" and j.of(hit) == "KZ"
        assert j.of(dict(hit, jurisdiction="")) == j.of({"designation": hit["designation"], "title": hit["title"]})
    finally:
        con.execute("UPDATE docs SET card=? WHERE code='N-00001'", (before,))
        con.commit()
        con.close()
