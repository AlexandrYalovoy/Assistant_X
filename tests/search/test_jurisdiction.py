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


def test_foreign_national_norms_are_a_supplement_and_first_when_named():
    """Russian-language and international norms govern; the American, European, British and German national norms
    come after them as a supplement, and first when the question names them."""
    j = J.load("oil-gas-ru")
    assert j.home == {"RU", "CIS", "EAEU", "KZ", "INT"} and {"US", "EU", "GB", "DE"} <= set(j.extra)
    assert [j.of(hit("N", d)) for d in ("EN 13480-3", "BS 7910", "DIN 2413", "СТ РК EN 1990")] == ["EU", "GB", "DE", "KZ"]
    res = [hit("N-1", "EN 13480-3"), hit("N-2", "ГОСТ Р 55990-2014"), hit("N-3", "DIN 2413"), hit("N-4", "ISO 13623")]
    assert [r["code"] for r in j.arrange(res, "толщина стенки трубопровода", 2)] == ["N-2", "N-4", "N-1", "N-3"]
    assert [r["code"] for r in j.arrange(res, "что требуют европейские нормы к толщине стенки", 2)][0] == "N-1"
    assert [r["code"] for r in j.arrange(res, "толщина стенки по DIN", 2)][0] == "N-3"


def test_a_question_naming_american_norms_puts_them_before_the_key_norms(monkeypatch):
    """«по ASME»: the American hits come before the key norms of the topic, which lead every other question."""
    from assistant_x.server import mcp_server as m

    class Lib:
        cfg = {"profile": "oil-gas-ru"}

        def search(self, query, k, **kw):
            return [hit("N-01887", "ASME B31.3", page=5), hit("N-00273", "ГОСТ 35070-2024", page=9)]

    monkeypatch.setattr(m, "lib", lambda: Lib())
    monkeypatch.setattr(m, "key_hits", lambda q: [hit("N-00421", "ГОСТ Р 55990-2014", page=56, key=True)])
    got = [r["code"] for r in m.find_fragments("толщина стенки трубы по ASME B31.3", 8, {})]
    assert got[0] == "N-01887" and "N-00421" in got
    got = [r["code"] for r in m.find_fragments("толщина стенки промысловой трубы", 8, {})]
    assert got[0] == "N-00421"  # a plain question: the key norm first, the American after the home ones


def test_a_plain_question_gets_the_foreign_norms_the_reranker_is_sure_of_after_the_answer(monkeypatch):
    from assistant_x.server import mcp_server as m

    class Lib:
        cfg = {"profile": "oil-gas-ru"}

        def search(self, query, k, jurisdictions=None, **kw):
            if jurisdictions:  # the supplement search
                return [hit("N-02004", "UFC 3-570-06", page=19, jurisdiction="US", sure=0.99),
                        hit("N-01887", "ASME B31G", page=2, jurisdiction="US", sure=0.95),
                        hit("N-01888", "ASME B36.10M", page=1, jurisdiction="US", sure=0.96),
                        hit("N-01999", "UFC 3-240-01", page=104, jurisdiction="US", sure=0.2)]  # fmt: skip
            return [hit("N-00278", "ГОСТ Р 51164-98", page=24), hit("N-01285", "ГОСТ 9.602-2016", page=19)]

    monkeypatch.setattr(m, "lib", lambda: Lib())
    monkeypatch.setattr(m, "key_hits", lambda q: [])
    got = m.find_fragments("защитный потенциал катодной защиты трубопровода", 8, {})
    assert [r["code"] for r in got] == ["N-00278", "N-01285", "N-02004", "N-01887"]  # two places for the US, sure ones
    assert [r.get("supplement") for r in got] == [None, None, "US", "US"]
    from assistant_x.server import quotes

    lines = quotes.lines("потенциал", [dict(r, text="Защитный потенциал -850 мВ.") for r in got])
    assert lines[-1].endswith("[US]") and not lines[0].endswith("]")


def test_a_filter_of_the_caller_holds_for_the_key_norms_and_the_supplement(monkeypatch):
    """jurisdictions=["KZ"]: no Russian key norm and no American supplement; a filter of genres or years: none of
    them; codes: only the documents asked for."""
    from assistant_x.server import mcp_server as m

    calls = []

    class Lib:
        cfg = {"profile": "oil-gas-ru"}

        def search(self, query, k, jurisdictions=None, codes=None, **kw):
            calls.append(jurisdictions)
            if jurisdictions and "US" in jurisdictions:
                return [hit("N-02004", "UFC 3-570-06", page=19, jurisdiction="US", sure=0.99)]
            return [hit("N-02200", "СН РК 3.05-01-2013", page=3, jurisdiction="KZ")]

    monkeypatch.setattr(m, "lib", lambda: Lib())
    monkeypatch.setattr(m, "key_hits", lambda q: [hit("N-00001", "ГОСТ Р 58367-2019", page=36, key=True)])
    assert [r["code"] for r in m.find_fragments("расстояния от факела", 8, {}, jurisdictions=["KZ"])] == ["N-02200"]
    assert [r["code"] for r in m.find_fragments("расстояния от факела", 8, {}, doc_types=["standard"])] == ["N-02200"]
    assert [r["code"] for r in m.find_fragments("расстояния от факела", 8, {}, codes=["N-02200"])] == ["N-02200"]
    got = [r["code"] for r in m.find_fragments("расстояния от факела", 8, {})]
    assert got == ["N-00001", "N-02200", "N-02004"]  # no filter: the key norm, the answer, the supplement


def test_a_short_ask_word_names_a_jurisdiction_only_as_a_whole_word():
    """Audit N-07: "energy", "end", "entry" are no EN norm; "EN 13480" and "API 5L" are."""
    j = J.load("oil-gas-ru")
    for q in ("energy consumption of the pump", "end of the pipeline", "entry pressure of a separator"):
        assert j.asked(q) == [], q
    assert j.asked("EN 13480 piping") == ["EU"] and j.asked("API 5L pipe") == ["US"]
    assert j.asked("американские нормы") == ["US"]
