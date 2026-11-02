# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdictions filter of the search and of list_documents (doc.jurisdiction of the cards, core/jurisdiction.py)."""



def test_the_search_filter(lib):
    """jurisdictions=[…] keeps the documents of those jurisdictions; a document without one is left out."""
    con = lib.con
    con.execute("SAVEPOINT juris")
    try:
        con.execute("UPDATE docs SET card=json_set(card, '$.doc.jurisdiction', 'RU') WHERE code='N-00002'")
        assert [d["code"] for d in lib.list_docs(jurisdictions=["ru"])] == ["N-00002"]
        assert lib.list_docs(jurisdictions=["KZ"]) == []
        res = lib.search("ГОСТ Р 00002-2024 сепаратор", dense=False, jurisdictions=["RU"])
        assert res and {r["code"] for r in res} == {"N-00002"}
        assert lib.search("сепараторов", dense=False, jurisdictions=["KZ"]) == []
    finally:
        con.execute("ROLLBACK TO juris")
        con.execute("RELEASE juris")
