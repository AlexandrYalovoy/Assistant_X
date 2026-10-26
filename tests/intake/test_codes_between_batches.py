# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Between batches: the codes of two batches built one after the other (the second gets the next free ones when the
first is applied in between), the library vocabulary rebuilt by every apply."""

import json


# ---------- the codes of batches built one after the other ----------


def batch(cfg, name, rel_title):
    from assistant_x.intake import pipeline as intake
    from assistant_x.intake.state import State
    from tests.intake.intake_fixtures import doc_line
    from tests.intake.test_intake_flow import GOST_MD

    work = cfg.work / name
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t = state.by_rel(rel_title)["tid"]
    (work / "md" / f"{t}.md").write_text(GOST_MD, encoding="utf-8")
    state.update(t, status="done", pages=2, ocr_pages=0, sha=name * 4, sha256=name * 16)
    state.con.close()
    (work / "meta.jsonl").write_text(
        json.dumps(doc_line(t, "N", "Сепараторы нефтегазовые", "Separators-" + name)) + "\n", encoding="utf-8"
    )
    return work, t


def test_two_batches_built_one_after_the_other_get_two_codes(project):
    """index/codes.json keeps the highest number given: the second build does not give the first one's code again."""
    from assistant_x.intake import build as intake_build

    root, cfg = project
    a, ta = batch(cfg, "a", "text.pdf")
    b, tb = batch(cfg, "b", "Сканы/scan.pdf")
    assert intake_build.build(cfg, a, date="2026-10-25") == 0 and intake_build.build(cfg, b, date="2026-10-25") == 0
    assert json.loads((a / "codes.json").read_text())[ta] == "N-00002"
    assert json.loads((b / "codes.json").read_text())[tb] == "N-00003"


def test_two_batches_built_before_either_is_applied(project):
    """A batch built without the marks of the numbers (before index/codes.json) has the code another batch took:
    the apply gives it the next free one."""
    from assistant_x.core import card as C
    from assistant_x.intake import apply as intake_apply, build as intake_build

    root, cfg = project
    a, ta = batch(cfg, "a", "text.pdf")
    b, tb = batch(cfg, "b", "Сканы/scan.pdf")
    assert intake_build.build(cfg, a, date="2026-10-25") == 0
    (cfg.index / C.CODES_FILE).unlink()
    assert intake_build.build(cfg, b, date="2026-10-25") == 0
    assert json.loads((a / "codes.json").read_text())[ta] == json.loads((b / "codes.json").read_text())[tb] == "N-00002"
    assert intake_apply.apply(cfg, a, date="2026-10-25") == 0
    assert intake_apply.apply(cfg, b, date="2026-10-25") == 0  # the code was taken meanwhile: the next free one
    assert json.loads((b / "codes.json").read_text())[tb] == "N-00003"
    cards = C.paths(cfg.index / "cards")
    assert {"N-00002", "N-00003"} <= set(cards)
    assert C.load(cards["N-00003"])["file"]["library"].split("/")[-1].startswith("N-00003_")
    assert len(list((cfg.library / "01_Standards").glob("N-0000[23]_*"))) == 2


def test_apply_rebuilds_the_library_vocabulary(project):
    from tests.intake.test_personal import one_document

    root, cfg = project
    assert not cfg.ocr_vocab.exists()
    one_document(cfg, "N")
    text = cfg.ocr_vocab.read_text(encoding="utf-8")
    assert text.startswith("# vocabulary of the recognition score: 2 documents")
