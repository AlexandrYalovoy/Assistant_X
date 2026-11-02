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
