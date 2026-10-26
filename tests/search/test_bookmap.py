# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bookmap.build for texts without numbered Markdown headings: the contents page with printed page numbers,
numbered lines of a plain text, lines in capitals; list items and tables are not taken for sections."""

from assistant_x.search import bookmap

FILLER = "Текст раздела без заголовков, обычный абзац про сепарацию газа и нефти.\n"


def titles(pages):
    return [(o[1], o[2]) for o in bookmap.build(pages)[0]]


def test_contents_page_with_printed_numbers():
    # printed page = PDF page - 2: the contents says 3, 5, 7, the sections lie on PDF 5, 7, 9
    pages = [
        (1, "Руководство"),
        (2, "СОДЕРЖАНИЕ\nВведение .......... 3\n1 Общие положения .......... 5\n2 Расчёт сепаратора .......... 7"),
    ]
    pages += [(n, FILLER) for n in (3, 4, 6, 8)]
    pages += [(5, "ВВЕДЕНИЕ\n" + FILLER), (7, "1 ОБЩИЕ ПОЛОЖЕНИЯ\n" + FILLER), (9, "2 РАСЧЁТ СЕПАРАТОРА\n" + FILLER)]
    pages.sort()
    assert titles(pages) == [("Введение", 5), ("1 Общие положения", 7), ("2 Расчёт сепаратора", 9)]


def test_numbered_lines_of_a_plain_text():
    pages = [
        (1, "5.1 Общие требования\n" + FILLER),
        (2, FILLER + "5.2 Требования к сепараторам\n" + FILLER),
        (
            3,
            "5.2.1 Газовые сепараторы\n"
            + FILLER
            + "1. Глубина погружения датчика\n2. Минимальная температура\n"  # a list, not sections
            + "5.2.2 Сепараторы должны быть оборудованы\nпредохранительными клапанами.\n"  # a clause going on
            + "|5.3|Таблица|\n",
        ),  # a table row
        (4, "2.5 МПа при температуре\n" + FILLER),
    ]  # a value out of order
    assert titles(pages) == [
        ("5.1 Общие требования", 1),
        ("5.2 Требования к сепараторам", 2),
        ("5.2.1 Газовые сепараторы", 3),
    ]
    assert bookmap.build(pages)[0][1][4] == 2  # level from the number


def test_capitals_and_too_little():
    pages = [
        (1, "КАТАЛОГ ПРОДУКЦИИ ЗАВОДА\n" + FILLER),
        (2, "КЛАПАНЫ ПРЕДОХРАНИТЕЛЬНЫЕ\n" + FILLER),
        (3, "ЗАДВИЖКИ КЛИНОВЫЕ\n" + FILLER),
        (4, "ОБРАТНЫЕ КЛАПАНЫ\n" + FILLER),
    ]
    assert [t for t, _ in titles(pages)] == [
        "КАТАЛОГ ПРОДУКЦИИ ЗАВОДА",
        "КЛАПАНЫ ПРЕДОХРАНИТЕЛЬНЫЕ",
        "ЗАДВИЖКИ КЛИНОВЫЕ",
        "ОБРАТНЫЕ КЛАПАНЫ",
    ]
    assert titles(pages[:2]) == []  # two sheets: no guessed outline
    assert titles([(1, "APPROVED BY\n"), (2, FILLER), (3, "STANDARD DRAWING\n")]) == []  # two lines are noise


def test_repeated_guess_keeps_the_first_in_order():
    heads = [("", "Б", 1, 1), ("", "А", 2, 1), ("", "Б", 3, 1), ("", "В", 4, 1)]
    assert bookmap._first(heads) == [("", "Б", 1, 1), ("", "А", 2, 1), ("", "В", 4, 1)]
