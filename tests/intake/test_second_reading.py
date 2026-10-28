# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The second reading of the intake (process.Batch.second_reading, keep_better): a PDF whose text came from its text
layer and scores low by its words is read again from its page images; the better text stays."""

from types import SimpleNamespace

from assistant_x.core.formats import write_pages_info
from assistant_x.intake import process
from assistant_x.intake.tools import ocr_score
from tests.corpus import documents

GARBLED = " ".join(["xqzv blorft ktrm wuvx plimq"] * 12)


class FakeState:
    def __init__(self, rows):
        self.rows = rows

    def get(self, tid):
        return dict(self.rows[tid])

    def update(self, tid, **kw):
        self.rows[tid].update(kw)


def batch(tmp_path, row, md, source="markdown"):
    (tmp_path / "md").mkdir()
    (tmp_path / "md" / "T0001.md").write_text(md, encoding="utf-8")
    write_pages_info(
        tmp_path / "md" / "T0001.pages.json", {1: {"source": source, "ocr_score": 50.0, "label": None, "flags": []}}
    )
    return SimpleNamespace(work=tmp_path, state=FakeState({"T0001": row}), base={"ocr": True})


def test_a_poor_layer_is_read_again_and_the_better_text_stays(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset(), frozenset()))
    poor = f"=== page 1 ===\n\n{GARBLED}\n"
    row = {"rel": "stroyinf/GOST 7360-82.pdf", "pages": 3}
    b = batch(tmp_path, row, poor)
    res = {"pages": 3, "ocr_pages": 1, "ocr_score": 54.0}
    assert process.Batch.second_reading(b, "T0001", row, res)
    st = b.state.get("T0001")
    assert (
        st["imgocr"] and st["layer_res"]["ocr_score"] == 54.0 and (tmp_path / "mdtmp" / "T0001" / "T0001.layer.md").exists()
    )
    assert not process.Batch.second_reading(b, "T0001", st, res)  # once only
    # the page images read better: their text stays
    clean = "=== page 1 ===\n\n" + " ".join(documents.sentences(760, 3)) + "\n"
    (tmp_path / "md" / "T0001.md").write_text(clean, encoding="utf-8")
    process.Batch.keep_better(b, "T0001", b.state.get("T0001"))
    st = b.state.get("T0001")
    assert (tmp_path / "md" / "T0001.md").read_text(encoding="utf-8") == clean and st["imgocr"] and not st["layer_text"]
    assert st["why"].startswith("a poor text layer: the page images read instead")


def test_the_layer_comes_back_when_the_page_images_read_worse(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset(), frozenset()))
    layer = "=== page 1 ===\n\n" + " ".join(documents.sentences(761, 3)) + " " + GARBLED + "\n"
    row = {"rel": "a.pdf", "pages": 2}
    b = batch(tmp_path, row, layer)
    assert process.Batch.second_reading(b, "T0001", row, {"pages": 2, "ocr_pages": 0, "ocr_score": 60.0})
    (tmp_path / "md" / "T0001.md").write_text(f"=== page 1 ===\n\n{GARBLED} {GARBLED}\n", encoding="utf-8")
    process.Batch.keep_better(b, "T0001", b.state.get("T0001"))
    st = b.state.get("T0001")
    assert (tmp_path / "md" / "T0001.md").read_text(encoding="utf-8") == layer
    assert st["imgocr"] is False and st["ocr_score"] == 60.0 and st["why"].startswith("the text layer kept")


def test_no_second_reading_for_a_good_text_a_scan_or_another_format(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_score, "load_vocab", lambda path=None: (frozenset(), frozenset()))
    clean = "=== page 1 ===\n\n" + " ".join(documents.sentences(762, 3)) + "\n"
    b = batch(tmp_path, {"rel": "a.pdf"}, clean)
    assert not process.Batch.second_reading(b, "T0001", {"rel": "a.pdf"}, {"pages": 2, "ocr_pages": 1})  # scores well
    b.state.rows["T0001"]["rel"] = "a.pdf"
    (tmp_path / "md" / "T0001.md").write_text(f"=== page 1 ===\n\n{GARBLED}\n", encoding="utf-8")
    write_pages_info(
        tmp_path / "md" / "T0001.pages.json", {1: {"source": "ocr", "ocr_score": 50.0, "label": None, "flags": []}}
    )
    assert not process.Batch.second_reading(b, "T0001", {"rel": "a.pdf"}, {"pages": 2})  # a pure scan: no layer
    write_pages_info(
        tmp_path / "md" / "T0001.pages.json", {1: {"source": "markdown", "ocr_score": 50.0, "label": None, "flags": []}}
    )
    assert not process.Batch.second_reading(b, "T0001", {"rel": "a.docx"}, {"pages": 2, "ocr_pages": 0})  # no PDF
    b.base["ocr"] = False
    assert not process.Batch.second_reading(b, "T0001", {"rel": "a.pdf"}, {"pages": 2, "ocr_pages": 0})  # no Tesseract
