# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reference mode of a small local model (server/quotes.py): every hit as one line «quote» — [code, PDF N], title;
the quote is the sentence or the table row with the most words of the question, a row with the header of its table."""

from assistant_x.server import quotes, toolsets

TABLE = """6.2.1.9 Скорости движения технологических потоков при определении диаметров технологических трубопроводов
разного назначения рекомендуется принимать по данным таблицы 1.

|Наименование потоков|Скорость, м/с|
|---|---|
|Нефть, эмульсия, масло смазочное, реагенты:||
|Газ на всасывании и нагнетании поршневого компрессора|Не более 10,0|
|Газуглеводородный в трубопроводах|5-20|

<!-- Start of picture text -->
газ<br>скорость<br>трубопровод
<!-- End of picture text -->
"""


def hit(text, **kw):
    return dict({"code": "N-00001", "page": 36, "title": "ГОСТ Р 58367-2019 Обустройство месторождений", "text": text}, **kw)


def test_a_table_row_comes_with_the_header_of_its_table():
    q = quotes.pick("скорость газа в трубопроводах", TABLE)
    assert q == "Наименование потоков | Скорость, м/с: Газуглеводородный в трубопроводах | 5-20"


def test_a_sentence_and_the_line_ready_to_copy():
    text = "Общие положения. Для газопроводов максимально-допустимая скорость газа в шлейфах до 20 м/с. Прочее."
    line = quotes.line("допустимая скорость газа", hit(text, label="19"))
    assert line == (
        "«Для газопроводов максимально-допустимая скорость газа в шлейфах до 20 м/с. Прочее.» — "
        "[N-00001, p. 19, PDF 36], ГОСТ Р 58367-2019 Обустройство месторождений"
    )


def test_cards_are_left_out_and_long_quotes_cut():
    assert quotes.line("газ", hit("Газ.", kind="card")) is None
    long = "Скорость газа " + "очень " * 200 + "конец."
    q = quotes.pick("скорость газа", long)
    assert len(q) <= quotes.QUOTE_CHARS + 1 and q.endswith("…")
    assert quotes.lines("газ", [hit("Газ в трубе."), hit("x", kind="card")]) == [
        "«Газ в трубе.» — [N-00001, PDF 36], ГОСТ Р 58367-2019 Обустройство месторождений"
    ]


def test_the_hint_of_the_reference_mode_asks_for_quotes_only():
    hint = toolsets.FORM_HINT
    assert "Reference mode" in hint and "nothing from yourself" in hint and "The library has no documents" in hint


def test_a_small_model_is_told_to_answer_after_three_searches():
    """With no system prompt Qwen searched six times, read pages and never answered: from the third search of a
    question on, the result starts with ANSWER_NOW; a pause starts a new question."""
    page = [{"type": "text", "text": "«q» — [N-00001, PDF 36], t"}]
    state = (0, None)
    for t in (0, 10):
        state, out = toolsets.search_budget(state, "search_library", page, t)
        assert out == page
    state, out = toolsets.search_budget(state, "search_library", page, 20)
    assert out[0]["text"].startswith("Searched 3 times: answer the user now") and out[1:] == page
    state, out = toolsets.search_budget(state, "read_pages", page, 30)
    assert out[0]["text"].startswith("Searched 3 times")
    state, out = toolsets.search_budget(state, "search_library", page, 30 + toolsets.QUESTION_GAP + 1)
    assert out == page and state[0] == 1  # a new question


def test_table_of_contents_lines_are_not_quoted_and_weigh_less():
    """A line of a table of contents names a subject and its page («Время пребывания 285»): the quote is the
    sentence that answers, and a fragment that is mostly such lines weighs less in the search (retrieval.toc_like)."""
    from assistant_x.search.retrieval import toc_like

    text = "Время пребывания 285 Конструирование трехфазных сепараторов 285\nВремя пребывания в сепараторе 2-3 мин."
    assert quotes.pick("время пребывания сепаратор", text) == "Время пребывания в сепараторе 2-3 мин."
    assert toc_like("Введение 3\nОбласть применения 5\nСепараторы 285\nНасосы 300\nОбщие положения ....... 7")
    assert not toc_like("|Газ|5-20|\n|Нефть|3|\nТаблица 1") and not toc_like("Скорость газа 5-20 м/с.")


def test_a_long_hit_is_shown_around_its_best_line_with_the_table_header():
    rows = "\n".join(f"|Поток {i}|{i}|" for i in range(60))
    text = (
        "Вступление.\n|Наименование потоков|Скорость, м/с|\n|---|---|\n"
        + rows
        + "\n|Газ углеводородный в трубопроводах|5-20|\n"
        + rows
    )
    got = quotes.window("скорость газа в трубопроводах", text, n=300)
    assert len(got) < 400 and "|Газ углеводородный в трубопроводах|5-20|" in got
    assert got.startswith("…\n|Наименование потоков|Скорость, м/с|\n…") and quotes.window("x", "short") == "short"


def test_the_source_warning_keeps_what_matters_for_a_citation():
    from assistant_x.server import mcp_server

    d = {
        "quality": "a scan, the text was recognized: check figures against the page image",
        "issue": "the English part of the card is not written yet — write the English title (priority: low) | "
        "3 pages with garbled recognition — improve the text: recognize those pages again (priority: low)",
    }
    assert mcp_server._warn(d) == (
        "\nSource quality: a scan, the text was recognized: check figures against the page image; "
        "3 pages with garbled recognition"
    )
    assert mcp_server._warn({"issue": "the English part of the card is not written yet — write it"}) == ""


def test_the_printed_page_from_the_headers_and_footers():
    """A number at the top or bottom that keeps one offset to the PDF page over 3 pages in a row; the header numbers
    of a designation, an offset of 0, a lone number and two fitting offsets give nothing."""
    from assistant_x.search.printed import detect

    body = "Текст пункта 4.4.18 о скорости газа, достаточно длинная строка, чтобы не быть колонтитулом страницы.\n"
    pages = {p: f"СП РК 4.03-101-2013*\n{body * 3}{p - 120}\n" for p in range(121, 126)}
    pages[126] = f"СП РК 4.03-101-2013*\n{body * 3}"  # no number: the run ends
    pages[127] = f"{body}7\n"  # a lone number
    pages.update({p: f"- {r} -\n{body}" for p, r in ((3, "i"), (4, "ii"), (5, "iii"))})
    pages.update({p: f"Страница {p}\n{body}" for p in range(10, 14)})  # the printed page is the PDF page
    pages.update({p: f"Пример №{p - 20}\n{body}" for p in range(30, 34)})  # a number inside a text: not a page
    pages.update({p: f"{body}**СТРАНИЦА  {p - 40}  ИЗ  191**\n" for p in range(50, 53)})
    got = detect(pages)
    assert not any(p in got for p in range(30, 34)) and got.get(51) == "11"
    assert {p: got.get(p) for p in range(121, 128)} == {
        121: "1",
        122: "2",
        123: "3",
        124: "4",
        125: "5",
        126: None,
        127: None,
    }
    assert got.get(5) == "iii" and not any(p in got for p in range(10, 14))
    assert detect({p: f"{p - 1}\n{body}{p + 5}" for p in range(1, 6)}) == {}  # two offsets fit: no guess


def test_one_form_of_a_reference_with_the_parts_known():
    """[code, cl. N, table N, p. N, PDF N]: the labels of the language of the answer, the parts not known left out."""
    assert quotes.cite("N-00001", 36, None, "6.2.1.9", "1", "ru") == "[N-00001, п. 6.2.1.9, табл. 1, PDF 36]"
    assert quotes.cite("N-00001", 36, "34", None, None, "en") == "[N-00001, p. 34, PDF 36]"
    assert quotes.cite("L-00015", 242) == "[L-00015, PDF 242]"
    page = TABLE.replace("|Наименование", "Таблица 1 - Скорость движения технологических потоков\n\n|Наименование", 1)
    got = quotes.line("скорость газа в трубопроводах", hit(page), "ru")
    assert got == (
        "«Газуглеводородный в трубопроводах | 5-20» (табл.: Наименование потоков | Скорость, м/с) — "
        "[N-00001, п. 6.2.1.9, табл. 1, PDF 36], ГОСТ Р 58367-2019 Обустройство месторождений"
    )


def test_no_clause_or_table_made_of_a_date_a_value_or_a_word():
    """Audit N-14: a date, a value at the start of a line and a caption without a number give no part."""
    assert quotes.place("01.07.2021 введен впервые", 0) == (None, None)
    assert quotes.place("2.5 m is the least gap", 0) == (None, None)
    assert quotes.place("4.3.5. При выборе диаметров", 0) == ("4.3.5", None)
    assert quotes.place("Таблица продолжение\n|a|b|", 1) == (None, None)
    assert quotes.place("Tables 1 and 2 show\n|a|b|", 1) == (None, None)
    assert quotes.place("Таблица А.1 - Скорости\n|a|b|", 1) == (None, "А.1")


def test_a_key_norm_quote_the_page_does_not_hold_is_never_shown():
    """Audit P-04: the evidence of a key norm with a recognition slip gives way to a line of the page itself."""
    page = "Для газопроводов максимально-допустимая скорость газа в шлейфах до 20 м/с."
    bad = hit(page, evidence="Для газопроводов | озном | мз/с 20 м/с", label=None)
    assert "озном" not in quotes.line("допустимая скорость газа", bad) and "до 20 м/с" in quotes.line(
        "допустимая скорость газа", bad
    )
    good = hit(page, evidence=page)
    assert quotes.line("допустимая скорость газа", good).startswith("«" + page)
