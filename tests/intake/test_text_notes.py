# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The notes on the quality of a text made again from the text in the library (intake/text_notes.py): the page flags
garbled and doubled, the text issues of the card and the recognition score of its file; the other issues stay."""

import json

from assistant_x.core import card
from assistant_x.core.formats import read_pages_info, write_pages_info
from assistant_x.intake import text_notes
from assistant_x.intake.tools import ocr_score
from tests.corpus import documents

GARBLED = " ".join(["xqzv blorft ktrm wuvx plimq"] * 10)  # words no vocabulary knows


def library(tmp_path, pages, issues, flags=None, score="91.0", fmt_score=0.5):
    """index/ of one document N-00001: its text of the pages, page file, card with the issues, ocr_quality.tsv."""
    idx = tmp_path / "index"
    (idx / "texts").mkdir(parents=True)
    (idx / "cards").mkdir()
    md = "".join(f"=== page {n} ===\n\n{t}\n\n" for n, t in enumerate(pages, 1))
    (idx / "texts" / "N-00001.md").write_text(md, encoding="utf-8")
    info = {
        n: {"source": "ocr", "ocr_score": 90.0, "label": None, "flags": (flags or {}).get(n, [])}
        for n in range(1, len(pages) + 1)
    }
    write_pages_info(idx / "texts" / "N-00001.pages.json", info)
    c = {
        "code": "N-00001",
        "schema": card.SCHEMA_VERSION,
        "doc": card.empty_doc(),
        "file": {
            **card.empty_file(),
            "issues": issues,
            "format": {"kind": "pdf_scan", "pages": len(pages), "ocr_pages": len(pages), "ocr_score": fmt_score},
        },
    }
    card.dump(c, idx / "cards" / "N-00001.json")
    rows = {"N-00001": {"code": "N-00001", "score": score, "pages_below_threshold": "0"}}
    ocr_score.write_tsv(idx / ocr_score.TSV_NAME, rows)
    return idx


def test_refresh_makes_the_notes_of_the_text_again(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset(), frozenset()))
    clean = " ".join(documents.sentences(760, 3))
    pages = [clean, clean + " " + clean, GARBLED, clean]
    stale = [
        {
            "what": "Every phrase of the extracted text appears twice (a plain and a bold copy)",
            "need": "x",
            "priority": "high",
        },
        {
            "what": "7 pages with garbled recognition (more than a quarter of the words unknown)",
            "need": "y",
            "priority": "low",
        },
        {"what": "No title page and no imprint in the scan", "need": "z", "priority": "low", "noted": "2026-10-26"},
    ]
    idx = library(tmp_path, pages, stale, flags={1: ["doubled", "formula"]})
    aside = tmp_path / "aside"
    r = text_notes.refresh(idx, "N-00001", "2026-10-28", aside=aside)
    info = read_pages_info(idx / "texts" / "N-00001.pages.json")
    assert info[1]["flags"] == ["formula"] and info[2]["flags"] == ["doubled"] and "garbled" in info[3]["flags"]
    c = card.load(idx / "cards" / "N-00001.json")
    whats = [i["what"] for i in c["file"]["issues"]]
    assert whats[0] == "No title page and no imprint in the scan"  # not an issue of the text: kept as it was
    assert "1 pages with garbled recognition (more than a quarter of the words unknown)" in whats
    assert any("appears twice" in w and w.startswith("every phrase of 1 pages") for w in whats)  # 1 of 4 pages
    assert not any(w.startswith("7 pages") or w.startswith("Every phrase of the extracted") for w in whats)
    assert c["file"]["format"]["ocr_score"] == 0.91 and r["score"] == (0.5, 0.91)
    assert sorted(p.name for p in aside.iterdir()) == ["N-00001.json", "N-00001.pages.json"]  # the old files first
    assert json.loads((aside / "N-00001.json").read_text(encoding="utf-8"))["file"]["format"]["ocr_score"] == 0.5
    again = text_notes.refresh(idx, "N-00001", "2026-10-29")
    assert again["changed"] == [] and again["flags"] == 0  # nothing more to change; the dates of the notes stay
    assert all(
        i.get("noted") in ("2026-10-26", "2026-10-28") for i in card.load(idx / "cards" / "N-00001.json")["file"]["issues"]
    )


def test_refresh_trial_run_and_a_missing_card(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset(), frozenset()))
    idx = library(tmp_path, [GARBLED], [])
    before = (idx / "cards" / "N-00001.json").read_bytes()
    r = text_notes.refresh(idx, "N-00001", dry_run=True)
    assert r["flags"] == 1 and len(r["changed"]) == 2 and (idx / "cards" / "N-00001.json").read_bytes() == before
    assert text_notes.refresh(idx, "N-00002") == {}
