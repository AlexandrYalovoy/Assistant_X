# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check_index.py on a sound mini library and on broken copies of its cards and texts; manifest.py --check."""

import os, shutil, subprocess, sys

import pytest

from assistant_x.search import check_index


def errors(cfg):
    rep, _ = check_index.check(cfg)
    return {kind for (level, kind) in rep.items if level == "error"}


def test_sound_library_passes(mini):
    assert errors(mini["cfg"]) == set()


@pytest.fixture
def broken(mini, tmp_path):
    """A copy of index to spoil; the originals stay where they are."""
    idx = shutil.copytree(os.path.join(mini["root"], "index"), tmp_path / "index")
    cfg = dict(mini["cfg"], catalog=str(idx / "CATALOG.md"), cards_dir=str(idx / "cards"), texts_dir=str(idx / "texts"))
    return cfg, idx


def test_card_against_the_schema_and_the_profile(broken):
    from assistant_x.core import card as C

    cfg, idx = broken
    p = idx / "cards" / "N-00002.json"
    c = C.load(p)
    del c["doc"]["title"]["ru"]  # the profile oil-gas-ru needs Russian too
    C.dump(c, p)
    assert "a card that does not pass the schema or the profile" in errors(cfg)


def test_broken_and_misnamed_cards(broken):
    cfg, idx = broken
    (idx / "cards" / "N-00009.json").write_text("{not json", encoding="utf-8")
    (idx / "cards" / "N-00002.json").rename(idx / "cards" / "N-00003.json")
    found = errors(cfg)
    assert "a card that cannot be read" in found and "the name of a card file is not its code" in found


def test_missing_texts(broken):
    cfg, idx = broken
    (idx / "texts" / "E-00001-02.md").unlink()
    (idx / "texts" / "N-00002.md").unlink()
    found = errors(cfg)
    assert "no text of a part its card names" in found and "no text of the document" in found


def test_empty_text(broken):
    cfg, idx = broken
    (idx / "texts" / "N-00002.md").write_text("", encoding="utf-8")
    assert 'no "=== page N ===" markers in the text' in errors(cfg)


def test_text_format(broken):
    """AX text 1: one marker per page of the PDF, in order (errors); CRLF, invisible characters, a .pages.json
    missing or with other pages (warnings)."""
    from assistant_x.core.formats import write_pages_info

    cfg, idx = broken
    t = idx / "texts"
    lf = {"encoding": "utf-8", "newline": "\n"}
    (t / "N-00001.md").write_text("=== page 1 ===\n\nа\n\n=== page 2 ===\n\nб\n", **lf)  # its PDF has 3 pages
    (t / "J-00001.md").write_text("=== page 1 ===\n\nа\n=== page 3 ===\n\nб\n=== page 2 ===\n\nв\n", **lf)
    (t / "N-00002.md").write_bytes(f"=== page 1 ===\r\n\r\nтекст{chr(0x200B)}\r\n".encode("utf-8"))
    page = {"source": "layer", "ocr_score": None, "label": None, "flags": []}
    write_pages_info(t / "E-00001.pages.json", {1: page, 2: page})
    write_pages_info(t / "E-00001-02.pages.json", {1: page})
    rep, _ = check_index.check(cfg)
    found = {(level, kind): texts for (level, kind), texts in rep.items.items()}
    assert found[("error", "the page markers of a text and the pages of its PDF differ")] == [
        "N-00001: 2 markers, 3 PDF pages"
    ]
    assert [x.split(":")[0] for x in found[("error", "page markers out of order")]] == ["J-00001.md"]
    assert found[("warning", "a text with CRLF line ends (the text format has LF)")] == ["N-00002.md"]
    assert found[("warning", "invisible characters in a text (zero width, text direction)")] == ["N-00002.md: 1"]
    assert found[("warning", "a .pages.json with other pages than its text")] == ["E-00001: 2 pages in it, 1 in the text"]
    missing = found[("warning", "a text without its .pages.json (what is known of its pages)")]
    assert "E-00001-02.md" not in missing and "N-00001.md" in missing
    no_files = {kind for (level, kind) in check_index.check(cfg, files=False)[0].items if level == "error"}
    assert "the page markers of a text and the pages of its PDF differ" not in no_files  # no originals looked at


def test_manifest_check(mini, tmp_path):
    """manifest.py works on the workspace given: a copy of the library, write the manifest, check it, spoil a file."""
    shutil.copytree(os.path.join(mini["root"], "library"), tmp_path / "library")
    (tmp_path / "index").mkdir()
    run = lambda *a: (
        subprocess.run(
            [sys.executable, "-I", "-m", "assistant_x.intake.manifest", *a],
            capture_output=True,
            env=dict(os.environ, PYTHONUTF8="1", AX_WORKSPACE=str(tmp_path)),
        ).returncode
    )
    assert run() == 0
    assert (tmp_path / "index" / "manifest.tsv").exists()
    assert run("--check") == 0
    pdf = next((tmp_path / "library").rglob("N-00001_*.pdf"))
    pdf.write_bytes(pdf.read_bytes() + b"%spoiled\n")
    assert run("--check") == 1
