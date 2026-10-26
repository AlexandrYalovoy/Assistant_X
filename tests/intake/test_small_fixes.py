# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The small items of audit 6: cpu_int8 off by default (M-002), the profile hint of intake_list (M-001), a word in
small caps read in both cases (M-032), the lines of a narrow table cell (M-016)."""

import pytest

from assistant_x.core import config
from assistant_x.intake.tools import assemble_md
from assistant_x.server import intake_tools


def test_cpu_int8_off_by_default():
    assert config.SEARCH["cpu_int8"] is False
    from pathlib import Path

    template = Path(config.__file__).resolve().parent.parent / "templates" / "assistant_x.toml"
    text = template.read_text(encoding="utf-8")
    assert "# cpu_int8 = false" in text and "the same vectors" not in text


@pytest.mark.parametrize(
    "word, want",
    [
        ("ИНгИбИТОРЫ", "ИНГИБИТОРЫ"),
        ("иНГибиторы", "ингибиторы"),
        ("ГОСТу", "ГОСТу"),  # an abbreviation with its ending
        ("СНиП", "СНиП"),  # four letters: not touched
        ("NaHCO", "NaHCO"),  # Latin letters: the English pack keeps CamelCase
        ("Ингибиторы", "Ингибиторы"),
    ],
)
def test_small_caps(word, want):
    assert assemble_md.tidy(word) == want


def test_narrow_cell_lines_joined():
    row = "|Значения<br>прокладочного<br>коэффициента|Тип<br>А|1,5<br>2,0|"
    assert assemble_md.tidy(row) == "|Значения прокладочного коэффициента|Тип<br>А|1,5<br>2,0|"
    assert assemble_md.tidy("Текст<br>вне таблицы") == "Текст<br>вне таблицы"  # only inside a table row


def test_profile_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **k: (None, {"profile": "general"}))
    names = ["Сепараторы нефти.pdf", "Насосы/ГОСТ 1234.pdf", "Скважины.docx", "Промысел/отчёт газ.pdf", "x.pdf"]
    hint = intake_tools.profile_hint(names)
    assert "oil-gas-ru" in hint and "ask the user" in hint
    assert intake_tools.profile_hint(["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"]) == ""
    monkeypatch.setattr(config, "load", lambda *a, **k: (None, {"profile": "oil-gas-ru"}))
    assert intake_tools.profile_hint(names) == ""  # the profile is in use already
