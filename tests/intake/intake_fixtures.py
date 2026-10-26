# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test project for the intake (used by conftest.py and the tests): a temporary copy of the folder layout with a small library and a inbox
holding generated files. The real inbox, library and index are never touched.

  text.pdf        three pages of Russian text with a ГОСТ designation (text layer)
  Сканы/scan.pdf  one page that is a picture only (needs OCR); Cyrillic folder and file names, as users have them
  Архив.zip       a PDF inside, unpacked beside the archive by intake.py run
  Письма/note.eml letter: moved to _to_delete
  doc.docx        made with LibreOffice when it is installed
The library holds one document, N-00001, with its JSON card; doc_line() gives a valid meta.jsonl line of a document
(the profile oil-gas-ru: English and Russian).
Heavy tests (the whole pipeline) carry @pytest.mark.slow: python -m pytest -m slow tests/intake
"""

import os, subprocess, zipfile
from pathlib import Path

import pytest

import pymupdf

FONTS = [
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
FONT = next((str(f) for f in FONTS if f.exists()), None)
GOST_PAGES = [
    "ГОСТ Р 99999-2020\n\nНАЦИОНАЛЬНЫЙ СТАНДАРТ\n\nСЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ\nОбщие технические требования\n\n"
    "Москва Стандартинформ 2020",
    "1 Область применения\n\nНастоящий стандарт распространяется на сепараторы нефтегазовые для отделения газа\n"
    "от нефти на объектах сбора и подготовки нефти на месторождениях.",
    "2 Требования\n\nСкорость газа в сечении аппарата не должна превышать допустимую, рассчитанную\n"
    "по плотности газа и нефти при рабочих давлении и температуре.",
]


TYPES = {"N": "standard", "L": "book", "E": "datasheet", "R": "regulation", "P": "project", "X": "other"}


def doc_line(tid, sec, title, en, **extra):
    """A meta.jsonl line of a document that passes the checks: the title in Russian and English, a summary, topics,
    keywords in both languages; extra fields (designation, year, replaces…) over it."""
    words = en.replace("-", " ")
    return {
        "tid": tid,
        "sec": sec,
        "doc_type": TYPES[sec],
        "en": en,
        "title": {"en": words, "ru": title},
        "lang": ["ru"],
        "summary": f"{words}: a document for the tests.",
        "topics": ["test"],
        "keywords": {"en": ["test"], "ru": ["тест"]},
        **extra,
    }


def claude_line(draft, en):
    """A draft of meta_draft.jsonl completed the way Claude completes it: the English file name, every searchable text in
    English and Russian, a summary, topics and keywords."""
    words = en.replace("-", " ")
    line = {k: v for k, v in draft.items() if v not in ("", None) and k not in ("draft", "question", "version_of")}
    both = lambda m, default: {"en": (m or {}).get("en") or default, "ru": (m or {}).get("ru") or default}
    line.update(
        en=en,
        title=both(draft.get("title"), words),
        summary=f"{words}: a document for the tests.",
        topics=["test"],
        keywords={"en": ["test"], "ru": ["тест"]},
        lang=draft.get("lang") or ["ru"],
    )
    if "designation" in line:
        line["designation"] = both(line["designation"], next(iter(line["designation"].values())))
    for key in ("toc", "units"):
        for x in line.get(key, []):
            x["title"] = both(x["title"], next(iter(x["title"].values())))
    return line


def old_card():
    """The card of the document the test library holds: N-00001."""
    from assistant_x.core import card as C

    return C.complete(
        {
            "schema": 1,
            "code": "N-00001",
            "section": "N",
            "doc_type": "standard",
            "doc": {
                "title": {"en": "Old standard", "ru": "Старый стандарт"},
                "lang": ["ru"],
                "summary": "An old standard on pipelines.",
                "topics": ["pipelines"],
                "keywords": {"en": ["pipeline"], "ru": ["трубопровод"]},
            },
            "file": {
                "library": "library/01_Standards/N-00001_GOST-1_Old.pdf",
                "text": "index/texts/N-00001.md",
                "format": {"kind": "pdf_text", "pages": 1},
            },
            "intake": {"date": "2026-01-01", "personal": False},
        }
    )


def text_pdf(path, pages, size=12):
    doc = pymupdf.open()
    for t in pages:
        page = doc.new_page()
        page.insert_text((60, 80), t, fontsize=size, fontname="ru", fontfile=FONT)
    doc.save(path)


def scan_pdf(path, text="СКАН СТРАНИЦЫ\nДавление насыщения нефти газом"):
    src = pymupdf.open()
    src.new_page().insert_text((60, 120), text, fontsize=26, fontname="ru", fontfile=FONT)
    pix = src[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def make_project(root, soffice=None):
    """Workspace under root (the batches in intake/work); returns its assistant_x.toml."""
    root = Path(root)
    inbox, lib, idx = root / "inbox", root / "library", root / "index"
    for d in ("_duplicates", "_to_delete", "_rejected"):
        (inbox / d).mkdir(parents=True)
    write(inbox / "_README.md", "Folder for new documents (test)\n")
    text_pdf(inbox / "text.pdf", GOST_PAGES)
    (inbox / "Сканы").mkdir()
    scan_pdf(inbox / "Сканы" / "scan.pdf")
    inner = root / "inner.pdf"
    text_pdf(inner, ["Руководство по эксплуатации\n\nНасос центробежный секционный ЦНС 60-330.\nПаспорт изделия."])
    with zipfile.ZipFile(inbox / "Архив.zip", "w") as z:
        z.write(inner, "Насос/паспорт.pdf")
    inner.unlink()
    write(inbox / "Письма" / "note.eml", "From: a@b.c\nSubject: test\n\nписьмо\n")
    if soffice:
        txt = root / "doc.txt"
        write(txt, "Технологический регламент установки подготовки нефти.\nРаздел 1. Общие сведения.\n")
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={(root / 'lo').as_uri()}",
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(inbox),
                str(txt),
            ],
            capture_output=True,
            timeout=300,
        )
        txt.unlink()
        (inbox / "doc.docx").exists() or pytest.skip("LibreOffice made no docx")
    # library: one document and its index
    (lib / "01_Standards").mkdir(parents=True)
    text_pdf(lib / "01_Standards" / "N-00001_GOST-1_Old.pdf", ["Старый стандарт о трубопроводах."])
    from assistant_x.core import card as C
    from assistant_x.search import catalog

    C.dump(old_card(), idx / "cards" / "N-00001.json")
    catalog.write(idx, "2026-01-01", {"profile": "oil-gas-ru"})
    write(idx / "texts" / "N-00001.md", "=== page 1 ===\n\nСтарый стандарт о трубопроводах промысловых и магистральных.\n")
    write(
        idx / "journal.md",
        "# Intake journal\n\n| Date | Source file | Size, bytes | SHA-256 | Code | File in the library | Status |\n"
        "|---|---|---|---|---|---|---|\n| 2026-01-01 | inbox\\old.pdf | 10 | 0123456789abcdef | N-00001 | "
        "library\\01_Standards\\N-00001_GOST-1_Old.pdf | done |\n",
    )
    from assistant_x.core import config

    # the paths of programs count only in the local file of this PC (core/config.read)
    write(
        config.local_of(root / "assistant_x.toml"),
        config.dumps({"intake": {"soffice": soffice or "-", "tesseract": "", "tessdata": "", "sevenzip": ""}}) + "\n",
    )
    cfg = {
        "profile": "oil-gas-ru",
        "paths": {"work": "intake/work", "reports": "intake/reports"},
        "intake": {
            "workers": 2,
            "ocr_threads": 1,
            "worker_memory_mb": 3000,
            "priority": "normal",
            "affinity": "all",
            "regulate": False,
            "timeouts": {"soffice": 300, "hidden": 300, "convert": 900, "unpack": 300},
        },
    }
    path = root / "assistant_x.toml"
    write(path, config.dumps(cfg) + "\n")
    return path
