# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The intake from inbox to the library in a temporary project: preparing the folder (letters, archives),
SHA duplicates, build and apply into a copy of the library. The fast test fills the state by hand instead of
converting; the slow one runs the whole pipeline (LibreOffice and Tesseract when installed)."""

import json, os, re, shutil
from pathlib import Path

import pytest

from assistant_x.intake import pipeline as intake
from assistant_x.intake import apply as intake_apply
from assistant_x.intake import build as intake_build
from assistant_x.intake import config as intake_cfg
from assistant_x.core import journal
from assistant_x.intake import metadraft
from assistant_x.intake import quality_report
from assistant_x.intake.state import State
from tests.intake.intake_fixtures import claude_line, doc_line

GOST_MD = (
    "=== page 1 ===\n\nГОСТ Р 99999-2020\n\nСЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ Общие технические требования\n\nМосква Стандартинформ 2020\n\n"
    "=== page 2 ===\n\n# 1 Область применения\n\n" + "Настоящий стандарт распространяется на сепараторы. " * 5 + "\n"
)


def tree(d):
    return sorted(
        os.path.relpath(os.path.join(dp, x), d).replace("\\", "/") for dp, dns, fns in os.walk(d) for x in dns + fns
    )


def test_prepare_build_apply(project):
    root, cfg = project
    inbox = cfg.inbox
    os.makedirs(inbox / "Копия")
    shutil.copy2(inbox / "text.pdf", inbox / "Копия" / "text.pdf")  # an exact copy: a duplicate by SHA-256
    work = cfg.work / "2026-10-23"
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    counts, events, problems = intake.prepare(cfg, state)
    assert counts["letters"] == 1 and counts["archives"] == 1 and counts["archive_files"] == 1 and not problems
    assert (inbox / "_to_delete" / "Письма" / "note.eml").exists() and (inbox / "_to_delete" / "Архив.zip").exists()
    assert (inbox / "Архив" / "Насос" / "паспорт.pdf").exists()
    assert intake.register(cfg, state) == 4
    tids = {r["rel"]: r["tid"] for r in state.all()}
    batch = intake.Batch(cfg, work, state, 0)
    assert batch.hash_all() == 1
    copy = state.get(tids["Копия/text.pdf"])
    assert copy["status"] == "dup" and copy["dup_of"] == tids["text.pdf"]
    # what the pool would produce: Markdown and the measures
    md = {
        "text.pdf": GOST_MD,
        "Сканы/scan.pdf": "=== page 1 ===\n\nСКАН\n",
        "Архив/Насос/паспорт.pdf": "=== page 1 ===\n\n# Паспорт насоса ЦНС 60-330\n\n" + "Насос центробежный. " * 10,
    }
    (work / "md").mkdir()
    for rel, text in md.items():
        (work / "md" / f"{tids[rel]}.md").write_text(text, encoding="utf-8")
        state.update(
            tids[rel], status="done", pages=len(re.findall(r"=== (?:page|стр\.) ", text)), ocr_pages=int("scan" in rel)
        )
    q = quality_report.report(work, state)
    assert q["docs"] == 3 and q["problem_docs"] == 1 and (work / "intake_quality.md").exists()
    assert metadraft.write_drafts(work, state) == 3
    drafts = {
        json.loads(ln)["tid"]: json.loads(ln) for ln in (work / "meta_draft.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert drafts[tids["text.pdf"]]["code_hint"] == "ГОСТ Р 99999-2020"

    meta = work / "meta.jsonl"
    meta.write_text(
        json.dumps({"tid": tids["text.pdf"], "sec": "N", "title": "x", "en": "X", "replaces": "N-9"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    assert intake_build.build(cfg, work) == 1 and not (work / "codes.json").exists()  # a bad code: nothing built
    lines = [
        claude_line(drafts[tids["text.pdf"]], "Oil-Gas-Separators"),
        doc_line(tids["Архив/Насос/паспорт.pdf"], "E", "Паспорт насоса", "Pump-Passport", au="Pump", year=2015),
        doc_line(tids["Сканы/scan.pdf"], "X", "Скан", "Scan"),
    ]
    meta.write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in lines), encoding="utf-8")
    assert intake_build.build(cfg, work, date="2026-10-23") == 0
    codes = json.loads((work / "codes.json").read_text(encoding="utf-8"))
    assert codes[tids["text.pdf"]] == "N-00002" and codes[tids["Архив/Насос/паспорт.pdf"]] == "E-00001"
    from assistant_x.core import card as C

    card = C.load(work / "out" / "cards" / "N-00002.json")
    assert C.validate(card, ["en", "ru"], ["N", "L", "P", "E", "R", "X"]) == []
    assert (
        card["doc"]["designation"] == {"ru": "ГОСТ Р 99999-2020", "en": "GOST R 99999-2020"}
        and card["doc_type"] == "standard"
    )
    f = card["file"]
    assert f["library"] == "library/01_Standards/N-00002_GOST-R-99999-2020_Oil-Gas-Separators.pdf" and len(f["sha256"]) == 64
    assert (
        f["format"] == {"kind": "pdf_text", "pages": 2}
        and f["text"] == "index/texts/N-00002.md"
        and f["source_name"] == "text.pdf"
    )
    assert card["intake"] == {"batch": "2026-10-23", "date": "2026-10-23", "personal": False}
    assert C.load(work / "out" / "cards" / "X-00001.json")["file"]["issues"][0]["what"].startswith("1 of 1 pages")

    before = tree(root)
    assert intake_apply.apply(cfg, work, dry=True, date="2026-10-23") == 0 and tree(root) == before
    assert intake_apply.apply(cfg, work, date="2026-10-23") == 0
    lib = cfg.library
    assert (lib / "01_Standards" / "N-00002_GOST-R-99999-2020_Oil-Gas-Separators.pdf").exists()
    assert (cfg.index / "cards" / "N-00002.json").exists() and not list((cfg.index / "cards").glob("*.md"))
    assert (lib / "04_Datasheets" / "E-00001_Pump_Pump-Passport_2015.pdf").exists()
    assert (lib / "99_Other" / "X-00001_Scan.pdf").exists()
    assert (inbox / "_duplicates" / "Копия" / "text.pdf").exists()
    # inbox: only the description and the service folders (empty folders removed)
    assert sorted(os.listdir(inbox)) == sorted(["_README.md", "_duplicates", "_to_delete", "_rejected"])
    idx = cfg.index
    cat = (idx / "CATALOG.md").read_text(encoding="utf-8")
    assert "Updated: 2026-10-23. Documents: 4." in cat and "| X-00001 | Скан |" in cat
    upd = (idx / "sources_to_update.md").read_text(encoding="utf-8")
    assert "Open items: 1." in upd and "| X-00001 | Скан | 1 of 1 pages have almost no text" in upd
    assert (idx / "texts" / "N-00002.md").read_text(encoding="utf-8") == GOST_MD
    ev = journal.read_events(idx / "intake_events.tsv")
    kinds = [journal.kind(r[6]) for r in ev]
    assert kinds.count("accepted") == 4 and kinds.count("duplicate") == 1 and kinds.count("to delete") == 2  # 1 old + 3 new
    assert "duplicate N-00002" in next(r[6] for r in ev if journal.kind(r[6]) == "duplicate")
    assert journal.is_current(idx) == (True, "")
    man = (idx / "manifest.tsv").read_text(encoding="utf-8")
    assert "N-00002_GOST-R-99999-2020_Oil-Gas-Separators.pdf" in man
    assert {r["status"] for r in state.all()} == {"applied"}
    assert intake_apply.apply(cfg, work) == 1  # a batch is applied once


def test_apply_refuses_taken_place(project):
    root, cfg = project
    work = cfg.work / "w"
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t = state.by_rel("text.pdf")["tid"]
    (work / "md" / f"{t}.md").write_text(GOST_MD, encoding="utf-8")
    state.update(t, status="done", pages=2, ocr_pages=0)
    (work / "meta.jsonl").write_text(
        json.dumps(doc_line(t, "L", "Сепараторы нефтегазовые", "Book", year=2020)) + "\n", encoding="utf-8"
    )
    assert intake_build.build(cfg, work) == 0
    (cfg.library / "02_Literature").mkdir()
    (cfg.library / "02_Literature" / "L-00001_Book_2020.pdf").write_bytes(b"busy")
    assert intake_apply.apply(cfg, work) == 1
    assert (cfg.inbox / "text.pdf").exists()  # nothing moved


def test_config_env_override(project, monkeypatch, tmp_path):
    root, cfg = project
    monkeypatch.setenv("AX_CONFIG", str(cfg.path))
    monkeypatch.setenv("AX_WORKERS", "7")
    monkeypatch.setenv("AX_INBOX", str(tmp_path / "another"))
    c = intake_cfg.load()
    assert c.workers == 7 and c.inbox == (tmp_path / "another").resolve() and c.library == (root / "library").resolve()
    assert c.soffice is None  # "-" in the test config: do not use LibreOffice


@pytest.mark.slow
def test_whole_pipeline(tmp_path):
    from tests.intake.intake_fixtures import make_project

    soffice = intake_cfg.find_soffice()
    path = make_project(tmp_path / "Проект", soffice)
    cfg = intake_cfg.load(path)
    assert intake.main(["--config", str(path), "run"]) == 0
    work = sorted(cfg.work.glob("20??-??-??"))[-1]
    state = State(work / "state.sqlite")
    rows = {r["rel"]: r for r in state.all()}
    n_docs = 4 if soffice else 3
    assert sum(r["status"] == "done" for r in rows.values()) == n_docs, {
        k: (r["status"], r.get("why")) for k, r in rows.items()
    }
    summary = (work / "summary.md").read_text(encoding="utf-8")
    assert f"done (text obtained) {n_docs}" in summary and "archives unpacked 1" in summary and "letters 1" in summary
    assert "Quality: documents" in summary
    assert (work / "intake_quality.md").exists()
    scan = rows["Сканы/scan.pdf"]
    assert scan["ocr_pages"] == 1
    if intake_cfg.can_ocr(cfg):  # the picture was read by Tesseract, with the word confidence and a score
        assert "давление" in (work / "md" / f"{scan['tid']}.md").read_text(encoding="utf-8").lower()
        assert scan["ocr_score"] > 50 and scan["ocr_conf"] > 50
        assert json.loads((work / "ocr" / f"{scan['tid']}.json").read_text(encoding="utf-8"))["pages"][0]["conf"] > 50
        assert "OCR score" in (work / "intake_quality.md").read_text(encoding="utf-8")
    else:
        assert scan["no_ocr_pages"] == 1
    drafts = [json.loads(ln) for ln in (work / "meta_draft.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(drafts) == n_docs
    meta = [claude_line(d, "Document-" + d["tid"]) for d in drafts]
    (work / "meta.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in meta), encoding="utf-8")
    assert intake.main(["--config", str(path), "build"]) == 0
    assert intake.main(["--config", str(path), "apply"]) == 0
    cat = (cfg.index / "CATALOG.md").read_text(encoding="utf-8")
    assert f"Documents: {1 + n_docs}." in cat
    assert sorted(os.listdir(cfg.inbox)) == sorted(["_README.md", "_duplicates", "_to_delete", "_rejected"])
    assert journal.is_current(cfg.index)[0]
    from assistant_x.intake.tools import ocr_score  # the scores of the new texts reach index/ocr_quality.tsv

    scores = ocr_score.read_tsv(cfg.index / ocr_score.TSV_NAME)
    assert len(scores) == n_docs and all(r["source"] == "intake" for r in scores.values())
    if soffice:  # the PDF made from the DOCX lies beside it
        assert list(Path(cfg.library).rglob("R-00001_*.pdf"))


def test_document_of_two_files_gets_parts_in_its_card(project):
    """A document and its part: one card with file.parts (code <code>-02, its own text), one folder in the library."""
    from assistant_x.core import card as C

    root, cfg = project
    work = cfg.work / "parts"
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t, s = state.by_rel("text.pdf")["tid"], state.by_rel("Сканы/scan.pdf")["tid"]
    (work / "md" / f"{t}.md").write_text(GOST_MD, encoding="utf-8")
    (work / "md" / f"{s}.md").write_text(
        "=== page 1 ===\n\n" + "Протокол испытаний сепаратора. " * 80 + "\n", encoding="utf-8"
    )
    state.update(t, status="done", pages=2, ocr_pages=0)
    state.update(s, status="done", pages=1, ocr_pages=1)
    state.con.close()
    meta = [
        doc_line(t, "N", "Сепараторы", "Separators", designation={"en": "GOST R 99999-2020", "ru": "ГОСТ Р 99999-2020"}),
        {"tid": s, "part": t, "what": "Trials"},
    ]
    (work / "meta.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in meta), encoding="utf-8")
    assert intake_build.build(cfg, work, date="2026-10-25") == 0
    card = C.load(work / "out" / "cards" / "N-00002.json")
    assert card["file"]["library"] == "library/01_Standards/N-00002_Separators/N-00002-01_Separators.pdf"
    part = card["file"]["parts"][0]
    assert part["code"] == "N-00002-02" and part["what"] == "Trials" and part["text"] == "index/texts/N-00002-02.md"
    assert part["library"] == "library/01_Standards/N-00002_Separators/N-00002-02_Trials.pdf"
    assert part["format"]["kind"] == "pdf_scan" and (work / "out" / "texts" / "N-00002-02.md").exists()
    assert intake_apply.apply(cfg, work, date="2026-10-25") == 0
    assert (cfg.library / "01_Standards" / "N-00002_Separators" / "N-00002-02_Trials.pdf").exists()


def test_a_failed_file_is_no_duplicate_when_it_comes_again(project):
    from assistant_x.core import journal
    from assistant_x.intake.prepare import known_hashes, sha256

    root, cfg = project
    sha = sha256(cfg.inbox / "text.pdf")[:16]
    events = cfg.index / "intake_events.tsv"
    row = ["2026-10-27", "inbox\\text.pdf", 100, sha, "—", "—", "error: the PDF does not open: broken xref"]
    journal.append_events(events, [row])
    assert sha not in known_hashes(cfg)
    work = cfg.work / "2026-10-28"
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.prepare(cfg, state)
    intake.register(cfg, state)
    tid = state.by_rel("text.pdf")["tid"]
    intake.Batch(cfg, work, state, 0).hash_all()
    assert state.get(tid)["status"] == "queued"  # processed in this batch
    journal.append_events(events, [[*row[:4], "N-00012", "library\\N\\text.pdf", "done"]])
    journal.append_events(events, [[*row[:4], "—", "inbox\\_duplicates\\", "duplicate of N-00013 (same content)"]])
    assert known_hashes(cfg)[sha] == "N-00013"  # a code, never the text of an error
    state.update(tid, sha256=None)
    intake.Batch(cfg, work, state, 0).hash_all()
    assert state.get(tid)["status"] == "dup" and state.get(tid)["dup_of"] == "N-00013"
    state.close()
