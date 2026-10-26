# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""eval.py: questions by group, the quoted phrase of the answer page, metrics on the mini base, the check against a
saved result."""

from assistant_x.search import eval as ev


def test_parse_groups(tmp_path):
    p = tmp_path / "q.md"
    p.write_text(
        "# Questions\n\n| Question | Where the answer is |\n|---|---|\n| first? | L-15:3-5 |\n\n## Journal\n\n"
        "| second | N-00001:2; E-00006-02:* |\n| no answer | ? |\n",
        encoding="utf-8",
    )
    qs = ev.parse(str(p))
    assert [(g, q) for g, q, _, _ in qs] == [("Questions", "first?"), ("Journal", "second")]
    assert qs[0][2] == [("L-15", 3, 5)] and qs[1][2] == [("N-1", 2, 2), ("E-6-02", 0, 10**6)]
    assert [x[3] for x in qs] == ["", ""]


def test_parse_phrase_cell(tmp_path):
    p = tmp_path / "q.md"
    p.write_text(
        '## Quotes\n\n| how is the rate taken? | N-00001:2 | "по табл. 1 с учётом" |\n'
        "| guillemets | N-00001:2 | «газового фактора» |\n"
        "| no quotes in the third cell | N-00001:2 | газового фактора |\n",
        encoding="utf-8",
    )
    assert ev.parse(str(p)) == [
        ("Quotes", "how is the rate taken?", [("N-1", 2, 2)], "по табл. 1 с учётом"),
        ("Quotes", "guillemets", [("N-1", 2, 2)], "газового фактора"),
    ]


def test_run_by_group(lib):
    qs = [
        ("A", "обводнённости газового фактора", [("N-1", 2, 2)], ""),  # the documents of the mini library are Russian
        ("B", "обводнённости", [("N-1", 2, 2), ("N-1", 3, 3)], ""),  # page 3 is found through «табл. 1» of page 2
        ("B", "совсем другое слово", [("L-99", 1, 1)], ""),
    ]
    res, times = ev.run(lib, qs, k=5, dense=False, out=lambda *_: None)
    assert res["A"]["page"] == 1 and res["A"]["mrr"] == 1
    assert res["B"]["n"] == 2 and res["B"]["page"] == 0.5 and res["B"]["all_places"] == 0.5
    assert res[""]["n"] == 3 and len(times) == 3
    assert res[""]["quote"] is None and res[""]["quotes"] == 0  # no question has a phrase


def test_quote_metric(lib):
    qs = [
        ("Quotes", "обводнённости газового фактора", [("N-1", 2, 2)], "С учетом   обводненности продукции"),
        ("Quotes", "обводнённости газового фактора", [("N-1", 2, 2)], "сепаратор вертикальный"),  # not on the page
        ("Quotes", "совсем другое слово", [("L-99", 1, 1)], "что угодно"),  # the answer page is not found at all
        ("Pages", "обводнённости", [("N-1", 2, 2)], ""),
    ]
    lines = []
    res, _ = ev.run(lib, qs, k=10, dense=False, out=lines.append)
    assert res["Quotes"]["quotes"] == 3 and abs(res["Quotes"]["quote"] - 1 / 3) < 1e-9
    assert res["Pages"]["quote"] is None and res[""]["quotes"] == 3
    assert any("the phrase is not on an answer page" in x for x in lines)
    assert "| Quotes | 3 |" in ev.table(res, 10) and "33% of 3 |" in ev.table(res, 10)


def test_worse_than_reference():
    ref = dict(page=0.80, mrr=0.60, places=0.50)
    assert ev.worse(dict(page=0.79, mrr=0.60, places=0.50), ref) == []  # within the tolerance
    assert ev.worse(dict(page=0.70, mrr=0.61, places=0.50), ref) == ["page: 0.800 → 0.700"]
    # the share of the quotes counts once both runs have it; an older saved run without it is no failure
    assert ev.worse(dict(page=0.80, mrr=0.60, places=0.50, quote=0.5), dict(ref, quote=0.75)) == ["quote: 0.750 → 0.500"]
    assert ev.worse(dict(page=0.80, mrr=0.60, places=0.50, quote=0.5), ref) == []
    assert ev.worse(dict(page=0.80, mrr=0.60, places=0.50, quote=None), dict(ref, quote=0.75)) == []


def test_questions_from_the_cards(dense):
    qs = ev.card_questions(dense)
    assert (
        "cards: en",
        "How is the flow rate of a well measured?",
        [("N-1", 0, 10**6)],
        "",
        ("N-00001", ev.CARD_KINDS),
    ) in qs
    units = {(g, q) for g, q, *_ in qs if g.startswith("units")}
    assert units == {
        ("units: en", "Sizing of gas separators"),
        ("units: ru", "Расчёт газовых сепараторов"),
        ("units: en", "Corrosion of field pipelines"),
        ("units: ru", "Коррозия промысловых трубопроводов"),
    }


def test_a_card_does_not_answer_its_own_question(dense):
    """Without the drop the card of N-00001 is an answer (a page of the document: code:*); with it, only a page of the
    text counts. The Russian title of a unit finds the page of its article by words, its unit left out."""
    q = "How is the flow rate of a well measured?"
    leaky, fair = {}, {}
    ev.run(dense, [("A", q, [("N-1", 0, 10**6)], "")], k=5, out=lambda *_: None, per_question=leaky)
    assert "N-00001:0" in leaky[q]["top"]
    qs = [x for x in ev.card_questions(dense) if x[1] in (q, "Расчёт газовых сепараторов")]
    res, _ = ev.run(dense, qs, k=5, out=lambda *_: None, per_question=fair)
    assert "N-00001:0" not in fair[q]["top"] and len(fair[q]["top"]) <= 5
    assert fair["Расчёт газовых сепараторов"]["top"][0] == "J-00001:2"  # the page of the article, not its unit
    assert res["units: ru"]["page"] == 1 and set(res) == {"cards: en", "units: ru", ""}


def test_eval_command_from_cards(dense, monkeypatch, tmp_path, capsys):
    import os, sys

    monkeypatch.setattr(ev, "BASELINE", str(tmp_path / "eval_baseline.json"))
    config = os.path.join(dense.cfg["workspace"], "assistant_x.toml")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval.py",
            "--config",
            config,
            "--from-cards",
            "--fast",
            "--k",
            "5",
            "--save",
            "--questions",
            str(tmp_path / "none.md"),
        ],
    )
    ev.main()
    out = capsys.readouterr().out
    assert "| cards: en | 1 |" in out and "| units: ru | 2 |" in out and '"fast_k5_cards"' in out
    import json

    saved = json.loads((tmp_path / "eval_baseline.json").read_text(encoding="utf-8"))
    assert "fast_k5_cards" in saved and "Models: bge-m3 " in out  # the revisions the run was measured with
    assert set(saved["fast_k5_cards_models"]) == {"bge-m3", "bge-reranker-v2-m3"}
