# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""A new version of a document of the library: found by its designation or its title, the draft puts the question,
"replaces" takes the code of the old one and puts the old original, card and text aside in inbox\\_to_delete,
"other_version" keeps both and makes the cards name each other."""

import json

from assistant_x.intake import apply as intake_apply
from assistant_x.intake import build as intake_build
from assistant_x.intake import metadraft
from assistant_x.intake import pipeline as intake
from assistant_x.intake import versions
from assistant_x.intake.state import State
from assistant_x.core import card as C
from tests.intake.intake_fixtures import doc_line, text_pdf

OLD_MD = (
    "=== page 1 ===\n\nГОСТ Р 99999-2015\n\nСЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ Общие технические требования\n\n"
    "Москва Стандартинформ 2015\n"
)
NEW_MD = (
    "=== page 1 ===\n\nГОСТ Р 99999-2020\n\nСЕПАРАТОРЫ НЕФТЕГАЗОВЫЕ Общие технические требования\n\n"
    "Взамен ГОСТ Р 99999-2015\n\nМосква Стандартинформ 2020\n"
)


def test_key_and_find():
    assert versions.key("ГОСТ Р 51858-2002") == versions.key("ГОСТ Р 51858–2020") == "ГОСТР51858"
    docs = [
        ("N-00001", "ГОСТ Р 51858-2002 Нефть. Общие технические условия", "ГОСТ Р 51858-2002"),
        ("L-00001", "Сепараторы нефтегазовые: расчёт и конструкция аппаратов", None),
    ]
    code, _, why = versions.find("ГОСТ Р 51858-2020", "ГОСТ Р 51858-2020 Нефть", docs)
    assert code == "N-00001" and "2002 in the library" in why
    assert versions.find(None, "Сепараторы нефтегазовые: расчёт и конструкция аппаратов (2-е изд.)", docs)[0] == "L-00001"
    assert versions.find("ГОСТ 1-2000", "Насосы шестерённые", docs) is None


def batch(cfg, name, files):
    """A batch of one or more files of inbox with their Markdown, drafts written against the library."""
    work = cfg.work / name
    (work / "md").mkdir(parents=True)
    for rel in files:
        text_pdf(cfg.inbox / rel, ["x"])
    state = State(work / "state.sqlite")
    intake.register(cfg, state)
    tids = {}
    for rel, md in files.items():
        t = state.by_rel(rel)["tid"]
        (work / "md" / f"{t}.md").write_text(md, encoding="utf-8")
        state.update(t, status="done", pages=1, ocr_pages=0)
        tids[rel] = t
    metadraft.write_drafts(work, state, index=cfg.index)
    state.con.close()
    return work, tids


def apply_batch(cfg, work, meta):
    (work / "meta.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in meta), encoding="utf-8")
    assert intake_build.build(cfg, work, date="2026-10-25") == 0
    assert intake_apply.apply(cfg, work, date="2026-10-25") == 0


def first_in_library(project, rel="gost_2015.pdf"):
    root, cfg = project
    for p in list(cfg.inbox.iterdir()):  # only the files of the test
        if p.is_file() and p.suffix == ".pdf":
            p.unlink()
    work, tids = batch(cfg, "w1", {rel: OLD_MD})
    t = tids[rel]
    apply_batch(
        cfg,
        work,
        [
            doc_line(
                t,
                "N",
                "Сепараторы нефтегазовые",
                "Separators",
                au="GOST-R-99999-2015",
                designation={"en": "GOST R 99999-2015", "ru": "ГОСТ Р 99999-2015"},
            )
        ],
    )
    return cfg


def test_replace_takes_the_code_and_puts_the_old_one_aside(project):
    cfg = first_in_library(project)
    cat = (cfg.index / "CATALOG.md").read_text(encoding="utf-8")
    code = next(c for c in ("N-00002", "N-00001") if f"| {c} | ГОСТ Р 99999-2015" in cat)
    old_file = next((cfg.library / "01_Standards").glob(f"{code}_*"))
    work, tids = batch(cfg, "w2", {"gost_2020.pdf": NEW_MD})
    t = tids["gost_2020.pdf"]
    draft = json.loads((work / "meta_draft.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert draft["version_of"] == code and "replaces" in draft["question"][0] and draft["supersedes"] == "ГОСТ Р 99999-2015"
    apply_batch(
        cfg,
        work,
        [
            doc_line(
                t,
                "N",
                "Сепараторы нефтегазовые",
                "Separators",
                au="GOST-R-99999-2020",
                replaces=code,
                designation={"en": "GOST R 99999-2020", "ru": "ГОСТ Р 99999-2020"},
            )
        ],
    )
    aside = cfg.inbox / "_to_delete" / "replaced_2026-10-25"
    assert (aside / old_file.name).exists() and not old_file.exists()
    assert C.load(aside / "index" / "cards" / f"{code}.json")["doc"]["designation"]["ru"] == "ГОСТ Р 99999-2015"
    assert C.load(cfg.index / "cards" / f"{code}.json")["doc"]["designation"]["ru"] == "ГОСТ Р 99999-2020"
    cat = (cfg.index / "CATALOG.md").read_text(encoding="utf-8")
    assert cat.count(f"| {code} |") == 1 and "ГОСТ Р 99999-2020" in cat and "ГОСТ Р 99999-2015" not in cat
    assert "2020" in (cfg.index / "texts" / f"{code}.md").read_text(encoding="utf-8")
    events = (cfg.index / "intake_events.tsv").read_text(encoding="utf-8")
    assert "to delete: replaced by a new version" in events and "a new version, the old one to delete" in events


def test_keep_both_links_the_cards(project):
    cfg = first_in_library(project)
    cat = (cfg.index / "CATALOG.md").read_text(encoding="utf-8")
    old = next(c for c in ("N-00002", "N-00001") if f"| {c} | ГОСТ Р 99999-2015" in cat)
    work, tids = batch(cfg, "w2", {"gost_2020.pdf": NEW_MD})
    apply_batch(
        cfg,
        work,
        [
            doc_line(
                tids["gost_2020.pdf"],
                "N",
                "Сепараторы",
                "Separators",
                au="GOST-R-99999-2020",
                other_version=old,
                designation={"en": "GOST R 99999-2020", "ru": "ГОСТ Р 99999-2020"},
            )
        ],
    )
    codes = json.loads((work / "codes.json").read_text(encoding="utf-8"))
    new = codes[tids["gost_2020.pdf"]]
    assert new != old
    assert C.load(cfg.index / "cards" / f"{new}.json")["doc"]["other_versions"] == [old]
    assert C.load(cfg.index / "cards" / f"{old}.json")["doc"]["other_versions"] == [new]


def test_replace_of_a_missing_code_is_refused(project):
    root, cfg = project
    work, tids = batch(cfg, "w3", {"gost_2020.pdf": NEW_MD})
    (work / "meta.jsonl").write_text(
        json.dumps(doc_line(tids["gost_2020.pdf"], "N", "Икс", "X", replaces="N-00777")) + "\n", encoding="utf-8"
    )
    assert intake_build.build(cfg, work, date="2026-10-25") == 1 and not (work / "codes.json").exists()
