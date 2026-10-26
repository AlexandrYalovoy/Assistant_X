# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Names that broke robocopy and Windows tools: intake_cfg.safe_name and safe_place."""

from assistant_x.intake import config as intake_cfg

NFD_I = "й"  # "й" from macOS: "и" + combining breve; the names below are Cyrillic file names as users have them


def test_safe_name():
    assert intake_cfg.safe_name(f"плавающи{NFD_I}-мост.png") == "плавающий-мост.png"
    assert intake_cfg.safe_name("-плавающий.png") == "плавающий.png"
    assert intake_cfg.safe_name("Том V(В) Инжиниринг резервуаров\u200b.pdf") == "Том V(В) Инжиниринг резервуаров.pdf"
    assert intake_cfg.safe_name(" ☝❗EXTERNAL❗ Re.msg") == "☝❗EXTERNAL❗ Re.msg"
    assert intake_cfg.safe_name("a?b.txt") == "a_b.txt"
    assert intake_cfg.safe_name("обычное имя.pdf") == "обычное имя.pdf"
    assert intake_cfg.safe_place("inbox\\_duplicates\\Хайсис\\x.pdf") == "inbox\\_duplicates\\Хайсис\\x.pdf"
    assert intake_cfg.safe_place("inbox\\_duplicates\\a\\") == "inbox\\_duplicates\\a\\"
