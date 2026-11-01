# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The attachments of a document (file.attachments): a workbook of its appendices or a calculation kept beside it in
the library under its code, not read nor searched, named by the card; the intake places it (a meta line "attach"),
and the check, the removal, the export and the new codes of an install take it with the document."""

import json, os, shutil, sys

from assistant_x.base import export as X, inspection as I, package as P
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import load_config
from assistant_x.intake import config as intake_cfg, ledger, manifest, meta_schema, remove
from assistant_x.intake.state import State
from assistant_x.search import check_index
from tests.search.conftest import make_library

SHEET = b"PK\x05\x06" + b"\0" * 18  # an empty zip: a workbook nobody reads


def errors_of(path):
    rep, _ = check_index.check(load_config(path))
    return rep.lines(levels=("error",)), rep.lines(levels=("warning",))


def with_attachment(root, path):
    """N-00002 of the mini library gets a workbook beside it, named by its card."""
    cards = os.path.join(root, "index", "cards")
    card = C.load(os.path.join(cards, "N-00002.json"))
    folder = os.path.dirname(card["file"]["library"])
    place = f"{folder}/N-00002_attachment-1_Appendix-9.xlsm"
    with open(os.path.join(root, *place.split("/")), "wb") as f:
        f.write(SHEET)
    card["file"]["attachments"] = [{"library": place, "source_name": "Appendix 9.xlsm", "what": "Appendix 9"}]
    assert C.validate(card) == []
    C.dump(card, os.path.join(cards, "N-00002.json"))
    return place


def test_the_paths_of_an_attachment_follow_the_code():
    card = {
        "code": "N-00002",
        "file": {
            "library": "library/01_Standards/N-00002_A.pdf",
            "text": "index/texts/N-00002.md",
            "attachments": [{"library": "library/01_Standards/N-00002_attachment-1_B.xlsm", "what": "Appendix 9"}],
        },
        "doc": {},
    }
    new, _ = C.remap(card, {"N-00002": "N-00007"})
    assert new["file"]["attachments"][0]["library"] == "library/01_Standards/N-00007_attachment-1_B.xlsm"
    assert ("library/01_Standards/N-00002_attachment-1_B.xlsm", "library/01_Standards/N-00007_attachment-1_B.xlsm") in (
        C.renames(card, {"N-00002": "N-00007"})
    )
    assert "Attachments beside it, not searched: Appendix 9" in C.brief(card)
    assert "attachment (not searched): library/01_Standards/N-00002_attachment-1_B.xlsm" in C.brief(card, ["file"])
    bad = dict(card, file=dict(card["file"], attachments=[{"library": "library/../../evil.xlsm"}]))
    assert I.unsafe_paths(bad) and not I.unsafe_paths(card)  # a package is data from someone else


def test_the_check_knows_the_attachments_and_the_files_no_card_names(tmp_path):
    root = str(tmp_path / "lib")
    path = make_library(root)
    place = with_attachment(root, path)
    stray = os.path.join(root, "library", "01_Standards", "N-00002_stray.xlsm")
    shutil.copy(os.path.join(root, *place.split("/")), stray)
    manifest.main(["--root", root])
    errors, warnings = errors_of(path)
    stray_lines = " ".join(warnings).split("no card names")[-1]
    assert not errors and "N-00002_stray.xlsm" in stray_lines and "attachment-1" not in stray_lines
    os.remove(os.path.join(root, *place.split("/")))
    errors, _ = errors_of(path)
    assert "an attachment is not on disk" in " ".join(errors)


def test_the_removal_and_the_export_take_the_attachment(tmp_path, monkeypatch):
    from assistant_x.search import build_index

    root = str(tmp_path / "lib")
    path = make_library(root)
    place = with_attachment(root, path)
    os.makedirs(os.path.join(root, "inbox"))
    manifest.main(["--root", root])
    monkeypatch.setattr(sys, "argv", ["build_index.py", "--config", path])
    build_index.main()
    out = tmp_path / "a.axbase"
    X.export(load_config(path), settings.load(path)[1], str(out), "test-a", "1.0", say=lambda s: None)
    with P.Package(out) as pkg:
        assert place in set(pkg.names()) and pkg.verify() == []
    assert remove.main(["N-00002", "--config", path]) == 0
    assert not os.path.exists(os.path.join(root, *place.split("/")))
    aside = os.path.join(root, "inbox", "_to_delete")
    assert any(f.endswith("attachment-1_Appendix-9.xlsm") for _, _, fs in os.walk(aside) for f in fs)


def test_the_intake_places_an_attachment_beside_its_document(project):
    from assistant_x.intake import apply as intake_apply
    from assistant_x.intake import build as intake_build
    from assistant_x.intake import metadraft
    from assistant_x.intake import pipeline as intake
    from tests.intake.intake_fixtures import claude_line, doc_line

    root, cfg = project
    (cfg.inbox / "Приложение 9.xlsm").write_bytes(SHEET)
    work = cfg.work / "2026-11-01"
    work.mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.prepare(cfg, state)
    intake.register(cfg, state)
    tids = {r["rel"]: r["tid"] for r in state.all()}
    sheet = tids["Приложение 9.xlsm"]
    state.update(sheet, status="skipped", why=ledger.set_aside_why("spreadsheets"))
    (work / "md").mkdir()
    md = "=== page 1 ===\n\n# Паспорт насоса ЦНС 60-330\n\n" + "Насос центробежный. " * 10
    for rel in ("text.pdf", "Сканы/scan.pdf", "Архив/Насос/паспорт.pdf"):
        (work / "md" / f"{tids[rel]}.md").write_text(md, encoding="utf-8")
        state.update(tids[rel], status="done", pages=1)
    metadraft.write_drafts(work, state)
    drafts = {
        json.loads(x)["tid"]: json.loads(x) for x in (work / "meta_draft.jsonl").read_text(encoding="utf-8").splitlines()
    }
    passport = tids["Архив/Насос/паспорт.pdf"]
    lines = [
        claude_line(drafts[tids["text.pdf"]], "Pump-Passport-A"),
        doc_line(passport, "E", "Паспорт насоса", "Pump-Passport", au="Pump", year=2015),
        doc_line(tids["Сканы/scan.pdf"], "X", "Скан", "Scan"),
        {"tid": sheet, "attach": passport, "what": "Приложение 9"},
    ]
    assert meta_schema.check({"T0009": {"tid": "T0009", "attach": "T0001"}}) == [
        "T0009: attach refers to T0001, which is not a document of this batch (a line with sec)"
    ]
    (work / "meta.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in lines), encoding="utf-8")
    assert intake_build.build(cfg, work, date="2026-11-01") == 0
    assert intake_apply.apply(cfg, work, date="2026-11-01") == 0
    code = json.loads((work / "codes.json").read_text(encoding="utf-8"))[passport]
    card = C.load(cfg.index / "cards" / f"{code}.json")
    (att,) = card["file"]["attachments"]
    name = f"{code}_attachment-1_Prilozhenie-9.xlsm"
    assert att["library"] == f"library/04_Datasheets/{name}" and att["what"] == "Приложение 9"
    assert att["source_name"] == "Приложение 9.xlsm" and len(att["sha256"]) == 64
    assert (cfg.library / "04_Datasheets" / name).exists()
    assert not (cfg.index / "texts" / f"{sheet}.md").exists() and not list((cfg.inbox / "_rejected").rglob("*.xlsm"))
    errors, warnings = errors_of(str(intake_cfg.load(cfg.path).path))
    # the texts of this test are made by hand (one page each): only what concerns the attachment is looked at here
    assert "attachment" not in " ".join(errors) and "no card names" not in " ".join(warnings)
