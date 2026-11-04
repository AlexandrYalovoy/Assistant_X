# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quote of a reference marked on its page and the references gathered into a folder (server/highlight.py):
only what the text layer of a page has is marked, the originals are not changed, a file there already is not
replaced without overwrite."""

import os

import pymupdf
import pytest

from assistant_x.server import highlight as hl

PAGE = (
    "4.4.18 The speed of gas shall be at most 7 m/s for low pressure pipelines, 15 m/s for medium pressure.<br>"
    "Table 1 - Speeds<br>Gas hydrocarbon in pipelines 5-20<br>Oil in pipelines 3"
)


def pdf(path, pages=2, scan=False):
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page()
        if scan:  # a scan: a picture, no text layer
            p.draw_rect(pymupdf.Rect(50, 50, 300, 120), fill=(0.5, 0.5, 0.5))
        else:
            p.insert_htmlbox(pymupdf.Rect(50, 50, 550, 300), PAGE + f"<br>{i + 1}")
    doc.save(path)
    doc.close()
    return str(path)


def test_a_quote_is_found_whole_in_parts_and_never_guessed(tmp_path):
    doc = pymupdf.open(pdf(tmp_path / "a.pdf"))
    page = doc[0]
    rects, status = hl.find(page, "The speed of gas shall be at most 7 m/s for low pressure pipelines")
    assert status == "marked" and rects
    rects, status = hl.find(page, "Gashydrocarbon in pipelines | 5-20")  # run together, a table row
    assert status == "marked" and len(rects) >= 2 and max(r.y1 for r in rects) - min(r.y0 for r in rects) < 40
    assert hl.find(page, "The speed of gas | a value the page has not")[1] == "partial"
    assert hl.find(page, "nothing of this is there") == ([], "none")
    scan = pymupdf.open(pdf(tmp_path / "s.pdf", scan=True))
    assert hl.find(scan[0], "The speed of gas") == ([], "none")


def test_the_references_of_an_answer():
    answer = (
        "Found: 2 documents.\n"
        "«Gas | 5-20» (table: Name | Speed) — [N-00001, cl. 6.2.1.9, table 1, PDF 36], GOST R 58367\n"
        "«At most 7 m/s.» — [N-02201, cl. 4.4.18, p. 15, PDF 135], SP RK\n"
        "Sources: [N-00001, PDF 36]; [E-00006-02, PDF 3]"
    )
    assert [r[:3] for r in hl.references([answer])] == [
        ("N-00001", 36, "Gas | 5-20"),
        ("N-02201", 135, "At most 7 m/s."),
        ("N-00001", 36, ""),
        ("E-00006-02", 3, ""),
    ]


def test_a_full_reference_as_an_answer_prints_it():
    """The user pastes the reference of an answer as it is: the code and the PDF page count, the other parts in either
    language are skipped; the quote of the line, when there is one."""
    assert hl.references(["покажи [N-00001, п. 6.2.1.9, табл. 1, стр. 30, PDF 36]"]) == [
        ("N-00001", 36, "", ", п. 6.2.1.9, табл. 1, стр. 30")
    ]
    assert hl.references(["show [E-00006-02, cl. 4.4.18, table 6, p. 15, PDF 135]"]) == [
        ("E-00006-02", 135, "", ", cl. 4.4.18, table 6, p. 15")
    ]
    labels = [("cl.", "table", "p."), ("п.", "табл.", "стр.")]
    assert hl.parts_of(", п. 6.2.1.9, табл. 1, стр. 30", labels) == ("6.2.1.9", "1")
    assert hl.parts_of(", cl. 5.9, p. 22", labels) == ("5.9", "")
    line = "«Газуглеводородный в трубопроводах | 5-20» (табл.: Наименование) — [N-00001, п. 6.2.1.9, табл. 1, PDF 36], ГОСТ"
    assert [r[:3] for r in hl.references([line])] == [("N-00001", 36, "Газуглеводородный в трубопроводах | 5-20")]


def test_a_folder_of_the_user_only(tmp_path):
    lib = tmp_path / "library"
    assert hl.safe_folder(str(tmp_path / "out"), [str(lib)]) == str(tmp_path / "out")
    for bad in ("relative\\out", str(lib / "x"), str(lib)):
        with pytest.raises(ValueError):
            hl.safe_folder(bad, [str(lib)])


def test_the_files_and_one_pdf_of_the_pages_cited(tmp_path):
    src = pdf(tmp_path / "N-00001_gost.pdf")
    before = open(src, "rb").read()
    out = tmp_path / "out"
    refs = [("N-00001", 1, "Gas hydrocarbon in pipelines | 5-20"), ("N-00001", 2, "not on the page"), ("N-00009", 1, "")]

    def originals(code):
        return (src, None) if code == "N-00001" else (None, f"No document {code} in the catalog.")

    args = (str(out), refs, originals, lambda c, p, q: f"<b>[{c}, PDF {p}]</b> Title", "References")
    marks = {"none": "not marked", "partial": "in part"}
    got = hl.export(*args, marks)
    assert got["files"] == [str(out / "N-00001_gost.pdf")] and got["marked"] == 1 and got["none"] == 1
    assert got["missing"] == ["N-00009: No document N-00009 in the catalog."] and open(src, "rb").read() == before
    book = pymupdf.open(got["pdf"])
    assert book.page_count == 2 and "[N-00001, PDF 1]" in book[0].get_text() and "not marked" in book[1].get_text()
    assert book[0].get_drawings() and os.path.basename(got["pdf"]).startswith("References — ")
    book.close()
    again = hl.export(*args, marks)
    assert again["exists"] and not again["files"] and again["pdf"] is None
    assert hl.export(*args, marks, overwrite=True)["pdf"] == got["pdf"]


def test_short_parts_only_as_whole_words_and_far_parts_count_as_missing(tmp_path):
    """Audit N-05, N-06: "10" is never marked inside "2010" or "100"; a part found far from the rest is not marked
    and the status says partial."""
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_htmlbox(pymupdf.Rect(50, 50, 550, 200), "Pressure 10<br>temperature 2010, 100 and 210")
    p.insert_htmlbox(pymupdf.Rect(50, 700, 550, 760), "Velocity of gas 20 m/s")
    rects, status = hl.find(p, "Pressure | 10")
    assert status == "marked" and len(rects) == 2 and all(r.y1 < 90 for r in rects)
    rects, status = hl.find(p, "Pressure 10 … Velocity of gas 20 m/s")
    assert status == "partial"


def test_the_quote_of_each_reference_and_the_runs_to_the_last_word():
    """Audit N-13, N-15."""
    line = "«alpha beta» — [N-00001, PDF 3], T1; see also [N-00002, PDF 7], T2"
    assert [r[:3] for r in hl.references([line])] == [("N-00001", 3, "alpha beta"), ("N-00002", 7, "")]
    assert hl.runs("one two three four five six seven eight nine")[-1].endswith("nine")


def test_no_network_device_or_linked_path_into_the_library(tmp_path):
    """Audit N-01, N-02: a share, a device path and a junction to the library are refused."""
    import subprocess

    lib = tmp_path / "library"
    lib.mkdir()
    for bad in (r"\\host\share\refs", "//host/share", "\\\\?\\" + str(lib / "x")):
        with pytest.raises(ValueError):
            hl.safe_folder(bad, [str(lib)])
    if os.name == "nt":
        link = tmp_path / "myrefs"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(lib)], check=True, capture_output=True)
        for bad in (str(link), str(link / "sub")):
            with pytest.raises(ValueError):
                hl.safe_folder(bad, [str(lib)])


def test_two_originals_of_one_name_and_a_protected_pdf(tmp_path):
    """Audit N-04, N-11: both copies kept (the code in front of each name); a PDF with a password is left out
    before anything is written."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    one, two = pdf(a / "Part 1.pdf"), pdf(b / "Part 1.pdf")
    locked = str(tmp_path / "locked.pdf")
    d = pymupdf.open(pdf(tmp_path / "plain.pdf"))
    d.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    d.close()
    files = {"N-00001": one, "N-00002": two, "N-00003": locked}
    refs = [("N-00001", 1, ""), ("N-00002", 1, ""), ("N-00003", 1, "")]
    got = hl.export(str(tmp_path / "out"), refs, lambda c: (files[c], None), lambda c, p, q: c, "References", {})
    assert sorted(os.path.basename(f) for f in got["files"]) == ["N-00001_Part 1.pdf", "N-00002_Part 1.pdf"]
    assert any(m.startswith("N-00003:") and "password" in m for m in got["missing"])
    assert pymupdf.open(got["pdf"]).page_count == 2


def test_a_moved_inbox_is_a_folder_of_the_library_too(tmp_path, monkeypatch):
    """Audit N-03: the folders of [paths] count wherever they are."""
    from types import SimpleNamespace

    from assistant_x.core import workspace
    from assistant_x.server import mcp_server

    inbox = tmp_path / "shared_inbox"
    w = SimpleNamespace(
        inbox=inbox, library=tmp_path / "lib", index=tmp_path / "ix", data=tmp_path / "d", db=tmp_path / "db"
    )
    monkeypatch.setattr(workspace, "current", lambda: w)
    monkeypatch.setattr(mcp_server, "lib", lambda: SimpleNamespace(cfg={}))
    with pytest.raises(ValueError):
        hl.safe_folder(str(inbox / "refs"), mcp_server.library_folders())


def test_the_page_shown_is_kept_as_a_file_to_open_at_full_size(tmp_path, monkeypatch):
    """The author, 2026-11-04: the chat of Claude Desktop shows the image of a tool as a small thumbnail; the image is
    also saved in the pages folder of the folder of the PC (the last 50) and the answer gives a link to open it."""
    from assistant_x.core import workspace
    from assistant_x.server import mcp_server

    monkeypatch.setattr(workspace, "machine_dir", lambda: tmp_path)
    p = mcp_server.keep_page("N-00580", 27, b"png-bytes", "png", marked=True)
    assert p.name == "N-00580 PDF 27 marked.png" and p.read_bytes() == b"png-bytes"
    assert p.as_uri().startswith("file:///") and "N-00580" in mcp_server.PAGE_LINK.format(
        code="N-00580", page=27, url=p.as_uri()
    )
    for i in range(mcp_server.PAGES_KEPT + 5):
        mcp_server.keep_page("N-00001", i + 1, b"x", "jpeg")
    assert len(list((tmp_path / "pages").iterdir())) == mcp_server.PAGES_KEPT


def test_a_clause_named_is_marked_whole_a_table_row_alone():
    """The author, 2026-11-04: «покажи [N-00580, п. 5.9, стр. 22, PDF 27]» marked only «2 - 6 м/с» of a clause that also
    names 20 м/с; a clause named without a table is marked whole, from its number to the next clause."""
    lines = [
        "5.8 Гидравлический расчет следует производить по методикам.",
        "",
        "5.9 Гидравлический расчет трубопроводов должен выполняться с учетом:",
        "- минимально-допустимой скорости газа в шлейфах (2 - 6 м/с);",
        "- максимально-допустимой скорости газа в шлейфах (~ 20 м/с);",
        "",
        "5.10 Прочее положение.",
        "22",
    ]
    text = "\n".join(lines)
    got = hl.clause_text(text, "5.9")
    assert got.startswith("5.9 Гидравлический") and "2 - 6 м/с" in got and "20 м/с" in got and "5.10" not in got
    assert hl.clause_text(text, "7.1") == ""
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_htmlbox(pymupdf.Rect(50, 50, 550, 700), "<br>".join(lines))
    rects, status = hl.find(p, got, whole=True)
    ys = sorted({round(r.y0) for r in rects})
    assert status == "marked" and len(ys) >= 3  # every line of the clause


def test_a_whole_clause_is_one_solid_mark_over_a_misread_word():
    """The author, 2026-11-04: clause 5.9 of a scan was marked with holes where the text layer misread a word; a whole
    clause is marked as one run, line by line, its misread words too, and nothing of the clause before it."""
    lines = [
        "5.8 Hydraulic calculation follows the approved methods of the company.",
        "5.9 The hydraulic calculation of pipelines takes into account:",
        "- the minimum gas velocity in the lines (2 - 6 m/s);",
        "- the maximum gas vel0city in the lines (~ 20 m/s);",
        "5.10 Other provisions of the standard.",
    ]
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_htmlbox(pymupdf.Rect(50, 50, 550, 700), "<br>".join(lines))
    clause = " ".join(x.replace("vel0city", "velocity") for x in lines[1:4])  # the clause as the text should read
    rects, status = hl.find(p, clause, whole=True)
    words = p.get_text("words")
    misread = next(w for w in words if w[4] == "vel0city")
    cx, cy = (misread[0] + misread[2]) / 2, (misread[1] + misread[3]) / 2
    assert status == "marked" and any(r.contains(pymupdf.Point(cx, cy)) for r in rects)
    first = next(w for w in words if w[4] == "5.8")
    assert not any(r.contains(pymupdf.Point((first[0] + first[2]) / 2, (first[1] + first[3]) / 2)) for r in rects)
    assert len({round(r.y0) for r in rects}) == 3  # one mark a line
