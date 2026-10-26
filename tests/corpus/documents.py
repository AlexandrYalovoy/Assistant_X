# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The golden corpus: small synthetic documents made by code (Russian and English text of our own, no copyrighted
content) with what the intake must get from each: phrases on given pages, headings, the genre, the designation, the
verdict of the duplicate check, and the source text of the scanned pages (for the OCR accuracy).

    make(folder) -> [case]   writes the files and returns the cases (dicts, the keys below)

A case: name, file (in inbox, or in the library for the case marked library), phrases {page: [phrases]}, headings
[titles], doc_type, designation, verdict (None, or (status, the name or code of the other document)), ocr_text {page:
the text rendered as a picture}, needs ("" | "ocr" | "soffice": what the text of the case needs), drawing (bool)."""

import html, random, zipfile
from pathlib import Path

import pymupdf

from tests.intake.intake_fixtures import FONT

WORDS = (
    "давление температура сепаратор нефть газ вода скважина трубопровод насос резервуар клапан задвижка датчик "
    "расход плотность вязкость обводненность дебит пласт эмульсия отстойник нагреватель компрессор фильтр "
    "измерение контроль испытание монтаж эксплуатация ремонт проверка давления температуры сепаратора нефти "
    "газа воды скважины трубопровода насоса резервуара клапана расхода плотности вязкости пласта эмульсии "
    "отстойника нагревателя компрессора фильтра устанавливают определяют проверяют поддерживают измеряют"
).split()
EN_WORDS = (
    "pressure temperature separator oil gas water well pipeline pump tank valve sensor flow density viscosity "
    "emulsion heater compressor filter measurement control test installation operation repair inlet outlet "
    "vessel level liquid vapour droplet residence time design capacity efficiency mesh vane coalescer"
).split()


def sentences(seed, n, words=WORDS):
    """n distinct sentences of 12 words: every phrase of five words is the document's own."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        w = [rng.choice(words) for _ in range(12)]
        out.append(f"{w[0].capitalize()} {' '.join(w[1:])} {i + 1}.")
    return out


def html_of(text):
    """A page of text as HTML: a line "# title" a heading, every other line a paragraph of its own."""
    out = []
    for line in text.split("\n"):
        if line.strip():
            out.append(f"<h3>{html.escape(line[2:])}</h3>" if line.startswith("# ") else f"<p>{html.escape(line)}</p>")
    return "".join(out)


def text_pdf(path, pages, size=10, rect=(56, 56, 540, 800), width=595, height=842):
    """A PDF typeset as a document is: headings bigger and bold, paragraphs apart (PyMuPDF's HTML box)."""
    doc = pymupdf.open()
    css = f"* {{font-family: sans-serif; font-size: {size}pt}} h3 {{font-size: {size + 3}pt; font-weight: bold}}"
    for t in pages:
        page = doc.new_page(width=width, height=height)
        page.insert_htmlbox(pymupdf.Rect(*rect), html_of(t), css=css)
    doc.save(path)
    return path


def picture_page(doc, text, dpi=150, noise=0.0, rotate=0, size=14, seed=1):
    """A page that is a picture of the text (a scan) at dpi; noise: share of the pixels made black; rotate: the
    picture put on the page turned by so many degrees."""
    src = pymupdf.open()
    src.new_page().insert_textbox(pymupdf.Rect(56, 56, 540, 800), text, fontsize=size, fontname="ru", fontfile=FONT)
    pix = src[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    if noise:
        rng = random.Random(seed)
        buf = bytearray(pix.samples)
        for _ in range(int(noise * len(buf))):
            buf[rng.randrange(len(buf))] = 0
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix.width, pix.height, bytes(buf), False)
    w, h = (842, 595) if rotate in (90, 270) else (595, 842)
    page = doc.new_page(width=w, height=h)
    page.insert_image(page.rect, pixmap=pix, rotate=rotate, keep_proportion=False)
    return page


SCAN_TEXT = (
    "Давление насыщения нефти газом определяют по пробам пластовой нефти.\n"
    "Пробы отбирают глубинным пробоотборником на забое скважины.\n"
    "Температуру пласта измеряют перед отбором каждой пробы."
)
STAMP = "КОПИЯ ВЕРНА. Документ предоставлен для служебного пользования, распечатан из системы документооборота."


def standard(path, designation, body, title="СЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ\nОбщие технические требования", author=None):
    pages = [
        f"НАЦИОНАЛЬНЫЙ СТАНДАРТ РОССИЙСКОЙ ФЕДЕРАЦИИ\n\n{designation}\n\n{title}\n\nМосква\nСтандартинформ\n"
        f"{designation[-4:]}"
    ]
    per = max(1, len(body) // 4)
    heads = ["1 ОБЩИЕ ПОЛОЖЕНИЯ", "1.1 Область применения", "2 ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ", "2.1 Конструкция"]
    for k, head in enumerate(heads):
        pages.append(f"# {head}\n" + " ".join(body[k * per : (k + 1) * per]))
    text_pdf(path, pages)
    if author:
        doc = pymupdf.open(path)
        doc.set_metadata({"author": author, "producer": author})
        doc.saveIncr()
    return heads


def docx(path, paragraphs):
    """A DOCX LibreOffice opens: [(style id or None, text)], styles 1 and 2 are Heading 1 and 2."""
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    styles = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {w}>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style></w:styles>'
    )
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        if s
        else f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
        for s, t in paragraphs
    )
    doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {w}><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="850" w:bottom="1134" '
        'w:left="1701" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.'
            'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/'
            'vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/'
            'xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="'
            'http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="'
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        z.writestr("word/styles.xml", styles)
        z.writestr("word/document.xml", doc)
    return path


def make(folder):
    """Write the corpus into folder (inbox/ and library/) and return its cases."""
    folder = Path(folder)
    inbox, lib = folder / "inbox", folder / "library"
    inbox.mkdir(parents=True, exist_ok=True)
    lib.mkdir(parents=True, exist_ok=True)
    cases = []

    def case(name, file, **kw):
        c = {
            "name": name,
            "file": file,
            "phrases": {},
            "headings": [],
            "doc_type": None,
            "designation": None,
            "verdict": None,
            "ocr_text": {},
            "needs": "",
            "drawing": False,
            "library": False,
            **kw,
        }
        cases.append(c)
        return c

    # 1 a clean text standard
    body = sentences(1, 16)
    heads = standard(inbox / "standard_clean.pdf", "ГОСТ Р 99001-2019", body)
    case(
        "standard_clean",
        "standard_clean.pdf",
        phrases={1: ["ГОСТ Р 99001-2019", "СЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ"], 3: [body[5]], 5: [body[12]]},
        headings=heads,
        doc_type="standard",
        designation="ГОСТ Р 99001-2019",
    )

    # 2 two columns (English)
    left, right = sentences(2, 8, EN_WORDS), sentences(3, 8, EN_WORDS)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(
        pymupdf.Rect(56, 56, 540, 120),
        "Two-phase separation in vertical vessels\nKeywords: separation, droplets",
        fontsize=12,
        fontname="ru",
        fontfile=FONT,
    )
    page.insert_textbox(pymupdf.Rect(56, 130, 290, 800), " ".join(left), fontsize=10, fontname="ru", fontfile=FONT)
    page.insert_textbox(pymupdf.Rect(305, 130, 540, 800), " ".join(right), fontsize=10, fontname="ru", fontfile=FONT)
    doc.save(inbox / "two_columns.pdf")
    case(
        "two_columns",
        "two_columns.pdf",
        phrases={1: [left[2], right[5], "Two-phase separation in vertical vessels"]},
        doc_type="article",
    )

    # 3 a table with a merged header cell
    doc = pymupdf.open()
    page = doc.new_page()
    put = lambda r, t, s=10: page.insert_textbox(pymupdf.Rect(*r), t, fontsize=s, fontname="ru", fontfile=FONT)  # noqa: E731
    put((56, 56, 540, 100), "Протокол испытаний № 5\nТаблица 1 — Дебит скважин", 12)
    for x in (56, 220, 380, 540):
        page.draw_line((x, 120 if x in (56, 540) else 140), (x, 260))
    for y in (120, 160, 200, 240, 260):
        page.draw_line((56 if y != 140 else 220, y), (540, y))
    page.draw_line((220, 140), (540, 140))
    put((60, 124, 215, 158), "Скважина")
    put((225, 122, 535, 138), "Показатели работы")
    put((225, 142, 375, 158), "Дебит, т/сут")
    put((385, 142, 535, 158), "Обводненность, %")
    rows = [("Скв-101", "12,5", "34"), ("Скв-102", "8,1", "56"), ("Скв-103", "15,0", "12")]
    for i, (a, b, c) in enumerate(rows):
        y = 164 + 40 * i
        put((60, y, 215, y + 30), a)
        put((225, y, 375, y + 30), b)
        put((385, y, 535, y + 30), c)
    doc.save(inbox / "table_merged.pdf")
    case(
        "table_merged",
        "table_merged.pdf",
        phrases={1: ["Таблица 1 — Дебит скважин", "Скв-102", "Обводненность, %"]},
        doc_type="report",
    )

    # 4 a formula page
    text_pdf(
        inbox / "formula.pdf",
        [
            "Расход газа через сепаратор определяют по формуле\n\nQ = k · F · ΔP (12)\n\n"
            "где k — коэффициент расхода, F — площадь сечения.\n" + " ".join(sentences(4, 6))
        ],
    )
    case("formula", "formula.pdf", phrases={1: ["Расход газа через сепаратор определяют по формуле", "(12)"]})

    # 5 a scanned page at 150 dpi, 6 a noisy and turned one
    doc = pymupdf.open()
    picture_page(doc, SCAN_TEXT)
    doc.save(inbox / "scan_150.pdf")
    case("scan_150", "scan_150.pdf", phrases={1: ["Давление насыщения нефти газом"]}, ocr_text={1: SCAN_TEXT}, needs="ocr")
    doc = pymupdf.open()
    picture_page(doc, SCAN_TEXT, noise=0.004, rotate=90, seed=6)
    doc.save(inbox / "scan_noisy_turned.pdf")
    case(
        "scan_noisy_turned", "scan_noisy_turned.pdf", phrases={1: ["пластовой нефти"]}, ocr_text={1: SCAN_TEXT}, needs="ocr"
    )

    # 7 a stamp in the text layer over a scan
    doc = pymupdf.open()
    page = picture_page(doc, SCAN_TEXT)
    page.insert_text((40, 30), STAMP, fontsize=6, fontname="ru", fontfile=FONT)
    doc.save(inbox / "stamp_over_scan.pdf")
    case(
        "stamp_over_scan",
        "stamp_over_scan.pdf",
        phrases={1: ["Давление насыщения нефти газом", "КОПИЯ ВЕРНА"]},
        ocr_text={1: SCAN_TEXT},
        needs="ocr",
    )

    # 8-10 two editions of one standard (the old one in the library) and a re-saved copy of the old one
    old = sentences(8, 60)  # enough phrases for the duplicate check (30 sampled ones at least)
    new = old[:42] + sentences(9, 18)  # 70 % of the text the same
    standard(lib / "edition_2002.pdf", "ГОСТ Р 51858-2002", old, "НЕФТЬ\nОбщие технические условия")
    case("edition_2002", "edition_2002.pdf", library=True, designation="ГОСТ Р 51858-2002", doc_type="standard")
    standard(inbox / "edition_2020.pdf", "ГОСТ Р 51858-2020", new, "НЕФТЬ\nОбщие технические условия")
    case(
        "edition_2020",
        "edition_2020.pdf",
        designation="ГОСТ Р 51858-2020",
        doc_type="standard",
        verdict=("suspect", "N-00001"),
        phrases={2: [new[1]]},
    )
    standard(
        inbox / "edition_2002_copy.pdf", "ГОСТ Р 51858-2002", old, "НЕФТЬ\nОбщие технические условия", author="Scanner 2"
    )
    case(
        "edition_2002_copy",
        "edition_2002_copy.pdf",
        designation="ГОСТ Р 51858-2002",
        doc_type="standard",
        verdict=("dup", "N-00001"),
    )

    # 11 a DOCX with heading styles
    paras = [(None, "Методические указания по контролю сепараторов"), ("1", "Общие положения")]
    paras += [(None, s) for s in sentences(11, 6)] + [("2", "Область применения")] + [(None, s) for s in sentences(12, 6)]
    paras += [("1", "Требования к оборудованию")] + [(None, s) for s in sentences(13, 6)]
    docx(inbox / "headings.docx", paras)
    case(
        "headings_docx",
        "headings.docx",
        headings=["Общие положения", "Область применения", "Требования к оборудованию"],
        doc_type="guideline",
        phrases={1: ["Методические указания по контролю сепараторов"]},
        needs="soffice",
    )

    # 12 a journal issue with two articles
    a1, a2 = sentences(14, 10), sentences(15, 10)
    text_pdf(
        inbox / "journal_issue.pdf",
        [
            "НЕФТЕГАЗОВОЕ ДЕЛО\nНаучно-технический журнал\nISSN 1234-5678\n№ 3, 2026",
            "Содержание\nСепарация нефти на промыслах ........ 3\nОсушка природного газа ........ 5\n"
            "Подготовка пластовой воды ........ 7",
            "# Сепарация нефти на промыслах\n" + " ".join(a1[:5]),
            " ".join(a1[5:]),
            "# Осушка природного газа\n" + " ".join(a2[:5]),
            " ".join(a2[5:]),
            "# Подготовка пластовой воды\n" + " ".join(sentences(16, 5)),
        ],
    )
    case(
        "journal_issue",
        "journal_issue.pdf",
        doc_type="serial_issue",
        headings=["Сепарация нефти на промыслах", "Осушка природного газа", "Подготовка пластовой воды"],
        phrases={3: [a1[1]], 5: [a2[0]]},
    )

    # 13 a drawing sheet: A3, a few words
    text_pdf(
        inbox / "drawing.pdf",
        ["Сборочный чертеж\nСепаратор НГС-1,6\nМасштаб 1:10   Лист 1   Листов 1\nРазраб. Петров"],
        size=14,
        rect=(700, 600, 1150, 820),
        width=1191,
        height=842,
    )
    case("drawing", "drawing.pdf", doc_type="drawing", drawing=True, phrases={1: ["Сборочный чертеж"]})

    # 14 a book with a printed contents page (page numbers two less than the PDF pages)
    ch = [sentences(20 + k, 8) for k in range(3)]
    text_pdf(
        inbox / "book.pdf",
        [
            "СПРАВОЧНИК ПО ПОДГОТОВКЕ НЕФТИ\n\nМосква: Недра, 1990\nУДК 622.276",
            "Содержание\nВведение ........ 1\nГлава 1. Свойства нефти ........ 2\nГлава 2. Сепарация нефти ........ 4",
            "# Введение\n" + " ".join(ch[0]),
            "# Глава 1. Свойства нефти\n" + " ".join(ch[1][:4]),
            " ".join(ch[1][4:]),
            "# Глава 2. Сепарация нефти\n" + " ".join(ch[2]),
        ],
    )
    case(
        "book_contents",
        "book.pdf",
        doc_type="book",
        headings=["Введение", "Глава 1. Свойства нефти", "Глава 2. Сепарация нефти"],
        phrases={4: [ch[1][1]]},
    )
    return cases
