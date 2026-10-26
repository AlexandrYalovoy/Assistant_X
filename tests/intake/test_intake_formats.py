# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The formats the intake processes besides PDF and office files: e-books (EPUB, FB2), texts (TXT in a legacy code
page, Markdown, HTML) laid out as PDF pages, spreadsheets (every sheet a Markdown table of the text), DjVu (skipped
with a note without DjVuLibre), the attachments of letters (.eml, Outlook .msg), and the outline a file gives
itself (PDF bookmarks, DOCX heading styles) as the first source of the contents. Every fixture is made here."""

import json, os, struct, zipfile
from email.message import EmailMessage

import pymupdf
import pytest

from assistant_x.core import textmap
from assistant_x.core.common import split_pages
from assistant_x.core.formats import read_outline, read_pages_info
from assistant_x.intake import metadraft, prepare
from assistant_x.intake import work as intake_work
from assistant_x.intake.state import State
from assistant_x.intake.tools import letters, outline, sheets
from tests.intake.intake_fixtures import text_pdf

BODY = "Давление насыщения нефти газом определяют по пробам пластовой нефти."


def job(tmp_path, src, ext, **kw):
    return {
        "work": str(tmp_path / "work"),
        "tid": "T0001",
        "ext": ext,
        "src": str(src),
        "soffice": None,
        "ddjvu": None,
        "ocr": False,
        "timeouts": {"soffice": 120, "hidden": 300, "convert": 600},
        "memory_mb": 3000,
        "env": dict(os.environ),
        "inproc": True,
        **kw,
    }


def prepped_text(tmp_path, res):
    doc = pymupdf.open(res["pdf"])
    return doc, "\n".join(p.get_text() for p in doc)


# ---------- e-books and texts ----------


def epub(path):
    chapters = [("Глава 1. Свойства нефти", BODY), ("Глава 2. Сепарация", "Сепараторы разделяют нефть и газ.")]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:'
            'opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="'
            'application/oebps-package+xml"/></rootfiles></container>',
        )
        items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(2))
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(2))
        nav = "".join(
            f'<navPoint id="n{i}" playOrder="{i + 1}"><navLabel><text>{t}</text></navLabel><content src="c{i}.xhtml"/>'
            f"</navPoint>"
            for i, (t, _) in enumerate(chapters)
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>'
            f'Книга</dc:title><dc:identifier id="id">x</dc:identifier></metadata><manifest>{items}<item id="ncx" '
            f'href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine toc="ncx">{spine}</spine></package>',
        )
        z.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            f'version="2005-1"><head/><docTitle><text>Книга</text></docTitle><navMap>{nav}</navMap></ncx>',
        )
        for i, (t, body) in enumerate(chapters):
            z.writestr(
                f"OEBPS/c{i}.xhtml",
                '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                f"<head><title>{t}</title></head><body><h1>{t}</h1>" + f"<p>{body}</p>" * 30 + "</body></html>",
            )
    return path


def test_epub_becomes_a_pdf_with_its_outline(tmp_path):
    src = epub(tmp_path / "book.epub")
    res = intake_work.prep(job(tmp_path, src, "epub"))
    assert res["status"] == "prepped" and res["pdf"].endswith("T0001.pdf") and res["pages"] >= 2
    doc, text = prepped_text(tmp_path, res)
    assert "Давление насыщения" in text and "Сепараторы разделяют" in text and res["ocr_pages"] == 0
    given = json.loads((tmp_path / "work" / "outline" / "T0001.json").read_text(encoding="utf-8"))
    assert [g[1] for g in given] == ["Глава 1. Свойства нефти", "Глава 2. Сепарация"] and given[0][2] == 1
    assert doc[0].rect.width == 595 and doc[0].rect.height == 842  # A4: the page numbers of a citation stay


def test_fb2_html_markdown_and_text(tmp_path):
    fb2 = (
        '<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
        f"<body><section><title><p>Введение</p></title><p>{BODY}</p></section></body></FictionBook>"
    )
    files = {
        "a.fb2": fb2.encode("utf-8"),
        "b.html": f"<html><meta charset='utf-8'><body><h1>Заголовок</h1><p>{BODY}</p></body></html>".encode("utf-8"),
        "c.md": f"# Заголовок\n\n{BODY}\n".encode("utf-8"),
        "d.txt": f"{BODY}\n".encode("cp1251"),
    }  # a legacy code page of the Russian pack
    for name, data in files.items():
        src = tmp_path / name
        src.write_bytes(data)
        w = tmp_path / name.replace(".", "_")
        res = intake_work.prep({**job(tmp_path, src, name.split(".")[1]), "work": str(w)})
        assert res["status"] == "prepped", (name, res)
        assert "Давление насыщения нефти газом" in "\n".join(p.get_text() for p in pymupdf.open(res["pdf"])), name


def test_decode_text_by_the_packs():
    assert intake_work.decode_text(BODY.encode("cp1251")) == BODY
    assert intake_work.decode_text(BODY.encode("koi8-r")) == BODY
    assert intake_work.decode_text(BODY.encode("utf-8")) == BODY
    assert intake_work.decode_text("\ufeff".encode("utf-16-le") + BODY.encode("utf-16-le")).lstrip("\ufeff") == BODY


def test_djvu_without_djvulibre_is_skipped_with_a_note(tmp_path):
    src = tmp_path / "scan.djvu"
    src.write_bytes(b"AT&TFORM\x00\x00\x00\x00DJVU")
    res = intake_work.prep(job(tmp_path, src, "djvu"))
    assert res["status"] == "skipped" and "DjVuLibre" in res["why"] and "ddjvu" in res["why"]


# ---------- spreadsheets ----------


def xlsx(path, sheets_rows):
    """A minimal workbook: shared strings and numbers, one sheet a dict of rows."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    strings = []
    with zipfile.ZipFile(path, "w") as z:
        sheet_types = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.'
            f'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(len(sheets_rows))
        )
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            f'spreadsheetml.sharedStrings+xml"/>{sheet_types}</Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        sh = "".join(f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(sheets_rows))
        z.writestr("xl/workbook.xml", f"<workbook {ns} {rns}><sheets>{sh}</sheets></workbook>")
        rels = "".join(
            f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml" Type="http://schemas.'
            f'openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            for i in range(len(sheets_rows))
        )
        rels += (
            '<Relationship Id="rIdS" Target="sharedStrings.xml" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/sharedStrings"/>'
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>',
        )
        for i, rows in enumerate(sheets_rows.values()):
            xml = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, v in enumerate(row):
                    ref = f"{chr(65 + c)}{r}"
                    if isinstance(v, str):
                        strings.append(v)
                        cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                xml.append(f'<row r="{r}">{"".join(cells)}</row>')
            z.writestr(
                f"xl/worksheets/sheet{i + 1}.xml", f"<worksheet {ns}><sheetData>{''.join(xml)}</sheetData></worksheet>"
            )
        si = "".join(f"<si><t>{s}</t></si>" for s in strings)
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{si}</sst>")
    return path


def test_spreadsheet_sheets_as_markdown_tables(tmp_path):
    book = xlsx(
        tmp_path / "book.xlsx", {"Скважины": [["Скважина", "Дебит, т/сут"], ["Скв-101", 12.5], ["Скв-102", 8]], "Пусто": []}
    )
    found = sheets.sheets_markdown(book)
    assert [n for n, _, _ in found] == ["Скважины"]
    assert found[0][1] == "| Скважина | Дебит, т/сут |\n|---|---|\n| Скв-101 | 12.5 |\n| Скв-102 | 8 |"
    assert "Скважина" in found[0][2]


def test_sheets_go_into_the_page_that_shows_them(tmp_path):
    w = tmp_path / "work"
    (w / "md").mkdir(parents=True)
    (w / "sheets").mkdir()
    (w / "md" / "T0001.md").write_text("=== page 1 ===\n\nОбложка\n\n=== page 2 ===\n\nСкважина Дебит\n", encoding="utf-8")
    (w / "md" / "T0001.pages.json").write_text(
        json.dumps(
            {
                "format": 1,
                "pages": {
                    "1": {"source": "layer", "ocr_score": None, "label": None, "flags": []},
                    "2": {"source": "layer", "ocr_score": None, "label": None, "flags": []},
                },
            }
        ),
        encoding="utf-8",
    )
    (w / "sheets" / "T0001.json").write_text(
        json.dumps([["Лист1", "| Скважина | Дебит |\n|---|---|\n| Скв-101 | 12 |", ["Скважина"]]], ensure_ascii=False),
        encoding="utf-8",
    )
    intake_work.finish_text(w, "T0001")
    pages = dict(split_pages((w / "md" / "T0001.md").read_text(encoding="utf-8")))
    assert "## Sheet: Лист1" in pages[2] and "| Скв-101 | 12 |" in pages[2] and "Sheet" not in pages[1]
    assert read_pages_info(w / "md" / "T0001.pages.json")[2]["flags"] == []


@pytest.mark.slow
def test_spreadsheet_through_libreoffice(tmp_path):
    from assistant_x.intake import config as intake_cfg

    exe = intake_cfg.find_soffice()
    if not exe:
        pytest.skip("no LibreOffice")
    import subprocess

    (tmp_path / "book.csv").write_text("Скважина;Дебит\nСкв-101;12.5\n", encoding="utf-8")
    subprocess.run(
        [
            exe,
            f"-env:UserInstallation={(tmp_path / 'lo').as_uri()}",
            "--headless",
            "--convert-to",
            "xlsx",
            "--infilter=CSV:59,34,76",
            "--outdir",
            str(tmp_path),
            str(tmp_path / "book.csv"),
        ],
        capture_output=True,
        timeout=300,
    )  # a workbook as LibreOffice writes it
    res = intake_work.prep(job(tmp_path, tmp_path / "book.xlsx", "xlsx", soffice=exe))
    assert res["status"] == "prepped" and res["pdf"].endswith("T0001.pdf"), res
    assert "Скв-101" in pymupdf.open(res["pdf"])[0].get_text()
    found = json.loads((tmp_path / "work" / "sheets" / "T0001.json").read_text(encoding="utf-8"))
    assert "| Скв-101 | 12.5 |" in found[0][1]


# ---------- letters ----------


def eml(path, pdf_bytes):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "Паспорт насоса", "a@example.com", "b@example.com"
    msg.set_content("Добрый день, паспорт во вложении.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="Паспорт насоса.pdf")
    path.write_bytes(bytes(msg))
    assert b"base64" in path.read_bytes()
    return path


def cfb(entries):
    """A minimal compound file (version 3) of a root, one storage and its streams: entries [(name, bytes)] of the
    storage "__attach_version1.0_#00000000"; a stream below 4096 bytes lies in the mini stream, as in Outlook files."""
    sec, end, free = 512, 0xFFFFFFFE, 0xFFFFFFFF
    small = [(n, d) for n, d in entries if len(d) < 4096]
    big = [(n, d) for n, d in entries if len(d) >= 4096]
    mini, starts = b"", {}
    for n, d in small:
        starts[n] = len(mini) // 64
        mini += d + b"\x00" * (-len(d) % 64)
    minifat = []
    for n, d in small:
        k = max(1, -(-len(d) // 64))
        minifat += [starts[n] + i + 1 for i in range(k - 1)] + [end]
    sectors, fat = [b""] * 3, [0xFFFFFFFD, end, end]  # 0 FAT, 1 directory, 2 mini FAT

    def put(data):
        first = len(sectors)
        k = max(1, -(-len(data) // sec))
        for i in range(k):
            sectors.append(data[i * sec : (i + 1) * sec].ljust(sec, b"\x00"))
            fat.append(first + i + 1 if i < k - 1 else end)
        return first

    mini_start = put(mini) if mini else end
    big_starts = {n: put(d) for n, d in big}

    def entry(name, kind, child=free, right=free, start=end, size=0):
        raw = (name + "\x00").encode("utf-16-le")
        return (
            raw.ljust(64, b"\x00")
            + struct.pack("<HBB", len(raw), kind, 1)
            + struct.pack("<III", free, right, child)
            + b"\x00" * 36
            + struct.pack("<IQ", start, size)
        )

    names = [n for n, _ in entries]
    sizes = dict(entries)
    dir_ = [
        entry("Root Entry", 5, child=1, start=mini_start, size=len(mini)),
        entry("__attach_version1.0_#00000000", 1, child=2),
    ]
    for i, n in enumerate(names):
        dir_.append(
            entry(
                n,
                2,
                right=3 + i if i + 1 < len(names) else free,
                start=starts[n] if n in starts else big_starts[n],
                size=len(sizes[n]),
            )
        )
    sectors[1] = b"".join(dir_).ljust(sec, b"\x00")[:sec]
    sectors[2] = struct.pack(f"<{sec // 4}I", *(minifat + [free] * (sec // 4 - len(minifat))))
    sectors[0] = struct.pack(f"<{sec // 4}I", *(fat + [free] * (sec // 4 - len(fat))))
    header = (
        letters.SIGNATURE
        + b"\x00" * 16
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
        + b"\x00" * 10
        + struct.pack("<IIII", 1, 1, 0, 4096)
        + struct.pack("<IIII", 2, 1, end, 0)
        + struct.pack("<109I", 0, *[free] * 108)
    )
    return header + b"".join(sectors)


def test_outlook_msg_attachment_is_taken_out(tmp_path):
    data = b"%PDF-1.4 " + bytes(range(256)) * 20  # past 4096 bytes: in the sectors, the name in the mini stream
    msg = tmp_path / "letter.msg"
    msg.write_bytes(cfb([("__substg1.0_37010102", data), ("__substg1.0_3707001F", "Паспорт.pdf".encode("utf-16-le"))]))
    assert letters.msg_attachments(msg.read_bytes()) == [("Паспорт.pdf", data)]
    rep = letters.extract(msg, tmp_path / "out")
    assert [p.split("\\")[-1].split("/")[-1] for p in rep["files"]] == ["Паспорт.pdf"] and not rep["error"]


def test_letter_attachments_become_documents_of_the_batch(project):
    root, cfg = project
    pdf = root / "p.pdf"
    text_pdf(pdf, [BODY])
    eml(cfg.inbox / "Письма" / "Паспорт.eml", pdf.read_bytes())
    work = cfg.work / "2026-10-25"
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    counts, events, problems = prepare.prepare(cfg, state)
    assert counts["letters"] == 2 and counts["letter_files"] == 1 and not problems  # note.eml of the fixture too
    assert (cfg.inbox / "Письма" / "Паспорт" / "Паспорт насоса.pdf").exists()
    assert (cfg.inbox / "_to_delete" / "Письма" / "Паспорт.eml").exists()
    assert any("its 1 attachments are in inbox\\Письма\\Паспорт" in e[6] for e in events)
    assert not (cfg.inbox / "_to_delete" / "Excel").exists()


# ---------- the outline the file gives ----------


def test_pdf_bookmarks_give_the_outline(tmp_path):
    pages = ["Обложка", "Введение " + BODY, "Свойства нефти " + BODY, "Сепарация " + BODY]
    path = tmp_path / "b.pdf"
    text_pdf(path, pages)
    doc = pymupdf.open(path)
    doc.set_toc([[1, "Введение", 2], [1, "Свойства нефти", 3], [2, "Сепарация", 4]])
    doc.saveIncr()
    given = outline.of_file(path)
    assert given == [[1, "Введение", 2], [1, "Свойства нефти", 3], [2, "Сепарация", 4]]
    rows, _ = textmap.build([(i + 1, t) for i, t in enumerate(pages)], given)
    assert [(r[1], r[2], r[3], r[4]) for r in rows] == [
        ("Введение", 2, 2, 1),
        ("Свойства нефти", 3, 4, 1),
        ("Сепарация", 4, 4, 2),
    ]
    assert textmap.build([(i + 1, t) for i, t in enumerate(pages)])[0] == []  # without it: no outline guessed here
    md = "".join(f"=== page {i + 1} ===\n\n{t}\n\n" for i, t in enumerate(pages))
    toc = metadraft.draft(md, "b.pdf", given=given)["toc"]
    assert [(t["pdf_from"], t["level"]) for t in toc] == [(2, 1), (3, 1), (4, 2)]


def docx(path, paragraphs):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    styles = (
        f'<w:styles {w}><w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 2"/></w:style></w:styles>'
    )
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        if s
        else f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"
        for s, t in paragraphs
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/styles.xml", styles)
        z.writestr("word/document.xml", f"<w:document {w}><w:body>{body}</w:body></w:document>")
    return path


def test_docx_heading_styles_found_on_their_pages(tmp_path):
    path = docx(
        tmp_path / "a.docx",
        [
            ("1", "Общие положения"),
            (None, BODY),
            ("2", "Область применения"),
            (None, BODY),
            ("1", "Требования к сепараторам"),
        ],
    )
    given = outline.docx_headings(path)
    assert given == [[1, "Общие положения", None], [2, "Область применения", None], [1, "Требования к сепараторам", None]]
    pages = [(1, "Общие положения\n" + BODY), (2, "Область применения\n" + BODY), (3, "Требования к сепараторам\n" + BODY)]
    assert [(h[1], h[2], h[3]) for h in textmap.given_heads(pages, given)] == [
        ("Общие положения", 1, 1),
        ("Область применения", 2, 2),
        ("Требования к сепараторам", 3, 1),
    ]


def test_outline_kept_in_pages_json(tmp_path):
    w = tmp_path / "work"
    (w / "md").mkdir(parents=True)
    (w / "outline").mkdir()
    (w / "md" / "T0001.md").write_text("=== page 1 ===\n\nТекст\n", encoding="utf-8")
    (w / "md" / "T0001.pages.json").write_text(
        json.dumps({"format": 1, "pages": {"1": {"source": "layer", "ocr_score": None, "label": None, "flags": []}}}),
        encoding="utf-8",
    )
    (w / "outline" / "T0001.json").write_text(json.dumps([[1, "Текст", 1]], ensure_ascii=False), encoding="utf-8")
    intake_work.finish_text(w, "T0001")
    assert read_outline(w / "md" / "T0001.pages.json") == [[1, "Текст", 1]]
    assert read_pages_info(w / "md" / "T0001.pages.json")[1]["source"] == "layer"


def test_base_keeps_the_outline_of_the_file(tmp_path):
    import sqlite3
    from assistant_x.search import bookmap

    con = sqlite3.connect(tmp_path / "b.sqlite")
    con.executescript(bookmap.SCHEMA)
    pages = [(1, "Обложка"), (2, "Введение " + BODY), (3, "Свойства нефти " + BODY)]
    bookmap.store_given(con, "N-00001", [[1, "Введение", 2], [1, "Свойства нефти", 3]])
    bookmap.store(con, "N-00001", pages)
    assert [r[0] for r in con.execute("SELECT title FROM outline WHERE code='N-00001' ORDER BY page")] == [
        "Введение",
        "Свойства нефти",
    ]


@pytest.mark.slow
def test_djvu_through_the_whole_intake_with_ocr(tmp_path):
    """A DjVu made by DjVuLibre's c44 (beside ddjvu) goes through the intake: ddjvu → PDF of page images → OCR."""
    import subprocess
    from pathlib import Path
    from assistant_x.intake import config as intake_cfg, pipeline
    from tests.corpus import documents
    from tests.intake.intake_fixtures import make_project

    ddjvu = intake_cfg.find_ddjvu()
    c44 = Path(ddjvu).with_name("c44.exe" if ddjvu and ddjvu.endswith(".exe") else "c44") if ddjvu else None
    if not (c44 and c44.exists() and intake_cfg.find_tesseract()):
        pytest.skip("the DjVu test needs DjVuLibre (ddjvu, c44) and Tesseract")
    path = make_project(tmp_path / "ws")
    cfg = intake_cfg.load(path)
    for f in list(cfg.inbox.rglob("*.*")):
        if f.parent.name not in ("_duplicates", "_to_delete", "_rejected") and f.name != "_README.md":
            f.unlink()
    doc = pymupdf.open()
    documents.picture_page(doc, documents.SCAN_TEXT, dpi=200)
    doc[0].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY).save(tmp_path / "p.pgm")
    subprocess.run(
        [str(c44), "-dpi", "200", str(tmp_path / "p.pgm"), str(cfg.inbox / "Скан.djvu")],
        check=True,
        capture_output=True,
        timeout=120,
    )
    assert pipeline.main(["--config", str(path), "run", "--workers", "0"]) == 0
    work = sorted(cfg.work.glob("20??-??-??"))[-1]
    row = next(r for r in State(work / "state.sqlite").all() if r["rel"] == "Скан.djvu")
    assert row["status"] == "done" and row["ocr_pages"] == 1 and row["ocr_conf"] > 50, row
    assert "давление насыщения" in (work / "md" / f"{row['tid']}.md").read_text(encoding="utf-8").lower()
    assert (work / "pdf" / f"{row['tid']}.pdf").exists()  # the PDF that goes beside the original
