# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal documents: [intake] personal = true (own documents next to a shared base package) marks the cards
(intake.personal); the codes are the same in both cases, the next free one of the shelf."""

import json

from assistant_x.core import card as C
from assistant_x.intake import pipeline as intake
from assistant_x.intake import apply as intake_apply
from assistant_x.intake import build as intake_build
from assistant_x.intake import config as intake_cfg
from assistant_x.intake.state import State
from tests.intake.intake_fixtures import doc_line
from tests.intake.test_intake_flow import GOST_MD


def one_document(cfg, sec="L"):
    """Build and apply text.pdf of the fixture as one document of the section; returns its code."""
    work = cfg.work / "w"
    (work / "md").mkdir(parents=True)
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    t = state.by_rel("text.pdf")["tid"]
    (work / "md" / f"{t}.md").write_text(GOST_MD, encoding="utf-8")
    state.update(t, status="done", pages=2, ocr_pages=0)
    (work / "meta.jsonl").write_text(
        json.dumps(doc_line(t, sec, "Сепараторы нефтегазовые", "Book", year=2020)) + "\n", encoding="utf-8"
    )
    assert intake_build.build(cfg, work, date="2026-10-25") == 0
    assert intake_apply.apply(cfg, work, date="2026-10-25") == 0
    return json.loads((work / "codes.json").read_text(encoding="utf-8"))[t]


def personal_project(root):
    path = root / "assistant_x.toml"
    intake_cfg.save({"personal": True}, path)
    return intake_cfg.load(path)


def test_plain_project(project):
    root, cfg = project
    assert cfg.personal is False and one_document(cfg, "N") == "N-00002"
    assert C.load(cfg.index / "cards" / "N-00002.json")["intake"]["personal"] is False


def test_personal_project_marks_the_cards(project):
    root, _ = project
    cfg = personal_project(root)
    assert cfg.personal is True and one_document(cfg, "N") == "N-00002"  # no range of its own: the next free code
    assert C.load(cfg.index / "cards" / "N-00002.json")["intake"]["personal"] is True
    assert list((cfg.library / "01_Standards").glob("N-00002_*"))
    assert "| N-00002 |" in (cfg.index / "CATALOG.md").read_text(encoding="utf-8")
