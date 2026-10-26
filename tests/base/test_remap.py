# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""New codes for documents (core/card.remap and renames, base/remap.py): every code field of a card, every file of a
document, the tables of the index; after a renumbering no old code is left in the live set and the history is
untouched. The marks of the code numbers (index/codes.json) and the lock of the code numbers. The registry of the
installed packages. The fingerprint cache of the duplicate check counts only for the same text."""

import json, os, re

import pytest

from assistant_x.core import card as C
from assistant_x.base import registry, remap as R
from tests.base import libraries


def test_map_code_path_and_text():
    m = {"N-00012": "N-00040", "E-00006": "E-00009"}
    assert C.map_code("N-00012", m) == "N-00040" and C.map_code("E-00006-02", m) == "E-00009-02"
    assert C.map_code("N-00013", m) == "N-00013" and C.map_code("not a code", m) == "not a code"
    assert (
        C.map_path("library/04_Datasheets/E-00006_Pump/E-00006-02_Trials.pdf", m)
        == "library/04_Datasheets/E-00009_Pump/E-00009-02_Trials.pdf"
    )
    assert C.map_path("index\\texts\\N-00012.pages.json", m) == "index\\texts\\N-00040.pages.json"
    assert C.map_path("library/01_Standards/XN-00012_x.pdf", m) == "library/01_Standards/XN-00012_x.pdf"
    assert (
        C.map_text("see N-00012, table 3, and E-00006-02; not AN-00012", m)
        == "see N-00040, table 3, and E-00009-02; not AN-00012"
    )


def test_check_mapping():
    assert C.check_mapping({"N-00001": "N-00002", "N-00002": "N-00001"}) == []
    assert C.check_mapping({"N-00001": "L-00001"})  # the shelf stays
    assert C.check_mapping({"N-00001-02": "N-00002-02"})  # documents only
    assert C.check_mapping({"N-00001": "N-00009", "N-00002": "N-00009"})


def test_remap_every_field_of_a_card(tmp_path):
    libraries.make_a(str(tmp_path))
    card = C.load(tmp_path / "index" / "cards" / "E-00001.json")
    card["file"]["hidden_text"] = [{"code": "E-00001-02", "fragments": 2}]
    card["file"]["issues"] = [
        {"what": "E-00001-02 has a torn page", "need": "", "priority": "low", "noted": "2026-10-23", "code": "E-00001-02"}
    ]
    card["doc"]["other_versions"] = ["E-00002"]
    card["doc"]["note"] = "The trials are E-00001-02."
    card["intake"]["package"] = {"id": "pkg", "version": "1", "code": "E-00001"}
    m = {"E-00001": "E-00007", "E-00002": "E-00008"}
    new, notes = C.remap(card, m)
    assert new["code"] == "E-00007" and new["file"]["parts"][0]["code"] == "E-00007-02"
    assert new["file"]["library"] == "library/04_Datasheets/E-00007_Test-Pump/E-00007-01_Manual.pdf"
    assert new["file"]["parts"][0]["text"] == "index/texts/E-00007-02.md"
    assert new["file"]["hidden_text"][0]["code"] == "E-00007-02" and new["file"]["issues"][0]["code"] == "E-00007-02"
    assert new["doc"]["other_versions"] == ["E-00008"] and new["doc"]["note"] == "The trials are E-00007-02."
    assert sorted(notes) == ["doc/note", "file/issues/0/what"]
    assert new["intake"]["package"]["code"] == "E-00001"  # the code in the package stays
    assert card["code"] == "E-00001"  # the card given is not changed
    assert C.validate(new, ("en", "ru")) == []
    moves = dict(C.renames(card, m))
    assert moves["index/cards/E-00001.json"] == "index/cards/E-00007.json"
    assert moves["index/texts/E-00001.md"] == "index/texts/E-00007.md"
    assert moves["index/texts/E-00001-02.pages.json"] == "index/texts/E-00007-02.pages.json"
    assert (
        moves["library/04_Datasheets/E-00001_Test-Pump/E-00001-02_Trials.pdf"]
        == "library/04_Datasheets/E-00007_Test-Pump/E-00007-02_Trials.pdf"
    )
    assert C.renames(card, {"N-00001": "N-00009"}) == []


def live_text(root):
    """Every name and every text of the live set of a workspace, as one string."""
    out = []
    for top in ("index", "library"):
        for dp, dns, fns in os.walk(os.path.join(root, top)):
            for f in fns:
                p = os.path.join(dp, f)
                out.append(os.path.relpath(p, root))
                if f.endswith((".json", ".md", ".tsv")) and f != "intake_events.tsv" and f != "journal.md":
                    # source_name: the name the original had before the intake, history like the events
                    out.append(re.sub(r'"source_name": "[^"]*"', "", open(p, encoding="utf-8").read()))
    for f in ("questions.md", "eval_baseline.json"):
        out.append(open(os.path.join(root, f), encoding="utf-8").read())
    return "\n".join(out)


def test_no_old_code_survives_a_renumbering(tmp_path):
    from assistant_x.core import journal
    from assistant_x.intake import manifest
    from assistant_x.intake.tools import dupcheck

    root = str(tmp_path / "A")
    libraries.make_a(root)
    manifest.main(["--root", root])
    journal.append_events(
        os.path.join(root, "index", "intake_events.tsv"),
        [["2026-10-23", "inbox\\pump.pdf", "1", "x", "E-00001", "library\\04_Datasheets\\E-00001_Test-Pump\\", "done"]],
    )
    history = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    libraries.write(
        os.path.join(root, "questions.md"),
        "| How is the rate measured? | N-1:2; E-00001-02:* |\n| Which pump? | E-00001:1 |\n",
    )
    libraries.write(os.path.join(root, "eval_baseline.json"), json.dumps({"words": {"ranks": {"E-00001:1": 1}}}))
    fp = os.path.join(root, ".assistant_x", "fingerprints")
    for code in ("N-00001", "N-00002", "E-00001"):
        dupcheck.library_fingerprint(os.path.join(root, "index", "texts", f"{code}.md"), fp)
    before = {
        c: open(os.path.join(root, "index", "texts", f"{c}.md"), encoding="utf-8").read()
        for c in ("N-00001", "N-00002", "E-00001-02")
    }
    m = {"N-00001": "N-00002", "N-00002": "N-00001", "E-00001": "E-00005"}  # a swap and a move
    libraries.renumber(root, m)

    text = live_text(root)
    assert not re.search(r"(?<![\w-])E-00001(?![\d])", text), "an old code survived"
    for old, new in (("N-00001", "N-00002"), ("N-00002", "N-00001"), ("E-00001-02", "E-00005-02")):
        assert open(os.path.join(root, "index", "texts", f"{new}.md"), encoding="utf-8").read() == before[old]
        assert C.load(os.path.join(root, "index", "cards", f"{C.main_code(new)}.json"))["code"] == C.main_code(new)
    assert "Test-Well-Rate" in C.load(os.path.join(root, "index", "cards", "N-00002.json"))["file"]["library"]
    assert os.path.exists(os.path.join(root, "library", "04_Datasheets", "E-00005_Test-Pump", "E-00005-02_Trials.pdf"))
    assert not os.path.exists(os.path.join(root, "library", "04_Datasheets", "E-00001_Test-Pump"))
    q = open(os.path.join(root, "questions.md"), encoding="utf-8").read()
    assert "N-00002:2; E-00005-02:*" in q and "E-00005:1" in q
    assert not os.listdir(fp)  # the fingerprints of the renumbered texts are gone
    # the history: the old rows as they were, one row per renumbered document after them
    events = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    assert events.startswith(history) and events.count("renumbered: ") == 3
    # manifest.py finds every renamed original unchanged: nothing hashed again
    rows = manifest.load(manifest.manifest_path(root))
    assert {r["code"] for r in rows.values()} >= {"N-00001", "N-00002", "E-00005-01", "E-00005-02"}
    from assistant_x.search import check_index
    from assistant_x.core.common import load_config

    assert check_index.run(load_config(os.path.join(root, "assistant_x.toml")), quiet=True) == 0
    assert C.high_water(os.path.join(root, "index"))["E"] == 5


def test_manifest_not_hashed_again_after_renumbering(tmp_path, capsys):
    from assistant_x.intake import manifest

    root = str(tmp_path / "A")
    libraries.make_a(root)
    manifest.main(["--root", root])
    libraries.renumber(root, {"N-00001": "N-00003"})
    capsys.readouterr()
    manifest.main(["--root", root])
    assert "hashed 0 (" in capsys.readouterr().out


def test_questions_with_a_code_in_another_script_are_listed():
    text, odd = R.questions_text("| q | Н-00001:2 |\n", {"N-00001": "N-00005"})
    assert odd == ["Н-00001"] and text == "| q | Н-00001:2 |\n"


def test_library_b_collides_with_a(tmp_path):
    libraries.make_a(str(tmp_path / "A"))
    libraries.make_b(str(tmp_path / "B"), package={"id": "pkg-b", "version": "1.0"})
    a, b = set(C.paths(tmp_path / "A" / "index" / "cards")), set(C.paths(tmp_path / "B" / "index" / "cards"))
    assert a & b == {"N-00001", "L-00001"} and b - a == {"P-00001"}
    card = C.load(tmp_path / "B" / "index" / "cards" / "P-00001.json")
    assert card["intake"]["package"] == {"id": "pkg-b", "version": "1.0", "code": "P-00001"}
    assert C.validate(card, ("en", "ru")) == []


def test_package_block_of_a_card_is_checked():
    card = libraries.C.complete(
        {
            "schema": 1,
            "code": "N-00001",
            "section": "N",
            "doc_type": "standard",
            "doc": {"title": {"en": "t"}, "lang": ["en"], "topics": ["x"], "summary": "s", "keywords": {"en": ["k"]}},
            "file": {"library": "", "format": {"kind": "other", "pages": None}, "text": ""},
            "intake": {
                "date": "2026-10-25",
                "personal": False,
                "package": {"id": "Bad Id", "version": "1", "code": "N-00001"},
            },
        }
    )
    assert any("package" in e for e in C.validate(card))
    card["intake"]["package"]["id"] = "good.id-1"
    assert C.validate(card) == []


# ---------- the numbers of the codes ----------


def test_high_water_never_lowers(tmp_path):
    assert C.high_water(tmp_path) == {}
    assert C.raise_high_water(tmp_path, ["N-00005", "E-00002-03"]) == {"N": 5, "E": 2}
    assert C.raise_high_water(tmp_path, ["N-00003"]) == {"N": 5, "E": 2}
    (tmp_path / C.CODES_FILE).write_text("not json", encoding="utf-8")
    assert C.high_water(tmp_path) == {}


def test_a_removed_number_is_not_given_again(tmp_path):
    from assistant_x.intake import build as intake_build

    cards = tmp_path / "index" / "cards"
    cards.mkdir(parents=True)
    C.raise_high_water(tmp_path / "index", ["N-00007"])  # N-00007 was given once and its document removed since
    assert intake_build.used_numbers(cards, {"t1": "N-00002"})["N"] == 7


def test_build_stops_without_the_code_lock(monkeypatch, capsys):
    from assistant_x.intake import build as intake_build
    from tests.intake.intake_fixtures import make_project
    import tempfile
    from pathlib import Path
    from assistant_x.intake import config as intake_cfg

    cfg = intake_cfg.load(make_project(Path(tempfile.mkdtemp(prefix="ax_lock_"))))
    work = cfg.work / "batch"
    work.mkdir(parents=True)
    (work / "meta.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(intake_build, "code_lock", lambda index, wait=120: None)
    assert intake_build.build(cfg, work) == 1
    assert "another process holds" in capsys.readouterr().out
    assert not (work / "codes.json").exists()


# ---------- the registry of the installed packages ----------


def test_registry(tmp_path):
    assert registry.load(tmp_path) == []
    registry.put(tmp_path, {"id": "b", "version": "1", "documents": 3})
    registry.put(tmp_path, {"id": "a", "version": "2"})
    registry.put(tmp_path, {"id": "b", "version": "1.1", "documents": 4})
    assert [(p["id"], p["version"]) for p in registry.load(tmp_path)] == [("a", "2"), ("b", "1.1")]
    assert registry.get(tmp_path, "b")["documents"] == 4
    assert registry.remove(tmp_path, "a") and not registry.remove(tmp_path, "a")
    with pytest.raises(ValueError):
        registry.put(tmp_path, {"id": "c"})


# ---------- the fingerprint cache of the duplicate check ----------


def test_fingerprint_cache_counts_only_for_the_same_text(tmp_path):
    from assistant_x.intake.tools import dupcheck

    words = " ".join(f"word{i} alpha{i} beta{i}" for i in range(400))
    other = " ".join(f"other{i} gamma{i} delta{i}" for i in range(400))
    texts, cache = tmp_path / "texts", tmp_path / "fp"
    texts.mkdir()
    (texts / "N-00001.md").write_text(words, encoding="utf-8")
    (texts / "N-00002.md").write_text(other, encoding="utf-8")
    fp1 = dupcheck.library_fingerprint(str(texts / "N-00001.md"), str(cache))
    fp2 = dupcheck.library_fingerprint(str(texts / "N-00002.md"), str(cache))
    assert fp1 and fp2 and fp1 != fp2
    # a renumbering: N-00002 goes away, N-00001 gets its text under the name N-00002 (the date of the file kept)
    st = os.stat(texts / "N-00001.md")
    os.remove(texts / "N-00002.md")
    os.replace(texts / "N-00001.md", texts / "N-00002.md")
    os.utime(texts / "N-00002.md", ns=(st.st_atime_ns, st.st_mtime_ns))
    assert dupcheck.library_fingerprint(str(texts / "N-00002.md"), str(cache)) == fp1
    (texts / "N-00003.md").write_text(words, encoding="utf-8")
    dupcheck.library_fingerprint(str(texts / "N-00003.md"), str(cache))
    assert (cache / "N-00003.fp").exists()
