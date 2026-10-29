# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A .chm help file as one document (tools/chm.py): the pages a help file holds in the order of its contents (.hhc),
each under its title, nothing that runs kept; laid out on A4 pages like any HTML (trial intake: 11 handbooks and books
of the inbox were files the intake did not process)."""

import pymupdf

from assistant_x.core.formats import file_kind
from assistant_x.intake.tools import chm
from assistant_x.intake.work import reflow_to_pdf

HHC = """<html><body><ul>
<li><object type="text/sitemap"><param name="Name" value="Введение"><param name="Local" value="html\\intro.htm"></object>
<li><object type="text/sitemap"><param name="Name" value="Глава 1. Кабели"><param name="Local" value="html/ch1.htm#top"></object>
</ul></body></html>"""


def _help(folder):
    (folder / "html").mkdir(parents=True)
    (folder / "toc.hhc").write_bytes(HHC.encode("cp1251"))
    (folder / "html" / "intro.htm").write_bytes(
        '<html><head><meta charset="windows-1251"><script>alert(1)</script></head><body><p>Справочник по кабелям '
        'и проводам.</p><img src="a.gif"></body></html>'.encode("cp1251")
    )
    (folder / "html" / "ch1.htm").write_bytes("<html><body><p>Кабель ВВГ: медные жилы.</p></body></html>".encode("utf-8"))
    (folder / "html" / "extra.htm").write_bytes(b"<html><body><p>Appendix</p></body></html>")


def test_the_pages_of_a_help_file_follow_its_contents(tmp_path):
    _help(tmp_path / "h")
    text, n, left = chm.assemble(tmp_path / "h", "Кабели")
    assert n == 3 and left == 0
    assert text.index("Введение") < text.index("Глава 1. Кабели") < text.index("Appendix")  # the rest after the contents
    assert "Справочник по кабелям" in text and "медные жилы" in text
    assert "<script" not in text and "alert" not in text and "<img" not in text


def test_a_help_file_is_laid_out_on_pages(tmp_path):
    _help(tmp_path / "h")
    page = tmp_path / "h.html"
    page.write_text(chm.assemble(tmp_path / "h", "Кабели")[0], encoding="utf-8")
    assert reflow_to_pdf(page, tmp_path / "h.pdf", "html") is None
    text = "".join(p.get_text() for p in pymupdf.open(tmp_path / "h.pdf"))
    assert "Справочник по кабелям" in text and "Кабель ВВГ" in text
    assert file_kind("Справочник.chm") == "ebook"


def test_no_7zip_leaves_a_help_file_skipped(tmp_path):
    rep = chm.to_html(tmp_path / "a.chm", tmp_path / "a.html", None, tmp_path / "a")
    assert rep["status"] == "skipped" and "7-Zip" in rep["why"]
