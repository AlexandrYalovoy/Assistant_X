# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x base inspect (base/inspection.py): what installing the package of library A would do in an empty
workspace, in library B (codes collide), in a copy of A (every document there already), and what stops it or warns:
the languages, the schema, damaged files, an intake batch not applied, long paths, the disk, Claude running."""

import json, os, shutil

import pytest

from assistant_x.base import export as X, inspection as I, package as P, registry
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import load_config
from tests.base import libraries
from tests.search.conftest import build, make_library, write
from tests.search.fake_embedder import embed


@pytest.fixture(scope="module")
def package_a(tmp_path_factory):
    """The package of library A (built and embedded with the fake model) as a zip, and its folder."""
    base = tmp_path_factory.mktemp("inspect")
    path = make_library(str(base / "A"))
    build(path)
    embed(path)
    cfg, raw = load_config(path), settings.load(path)[1]
    out = str(base / "a.axbase")
    X.export(cfg, raw, out, "test-a", "1.0", say=lambda s: None)
    X.export(cfg, raw, str(base / "a-folder"), "test-a", "1.0", folder=True, say=lambda s: None)
    return {"zip": out, "folder": str(base / "a-folder"), "library": path}


def workspace(root, kind):
    """A workspace to install into: "empty", "B" (library B) or "A" (a copy of library A)."""
    if kind == "empty":
        write(os.path.join(root, "assistant_x.toml"), 'profile = "general"\n[documents]\nlanguages = ["en"]\n')
        return os.path.join(root, "assistant_x.toml")
    if kind == "B":
        return libraries.make_b(root)
    return make_library(root)


def run(path, pkg, **kw):
    w, raw = settings.load(path)
    return I.inspect(load_config(path), raw, pkg, work=str(w.work), **kw)


def test_into_an_empty_workspace(package_a, tmp_path):
    r = run(workspace(str(tmp_path / "ws"), "empty"), package_a["zip"])
    assert r["ok"], r["problems"]
    assert r["codes"]["keeper"] == "package" and r["codes"]["mapping"] == {} and r["codes"]["recommended"] is None
    assert r["compatibility"]["adopt"] == {"profile": "oil-gas-ru", "card_languages": ["en", "ru"]}
    assert r["package"]["documents"] == 5 and r["library"]["documents"] == 0 and r["matches"] == []
    assert r["questions"] == [] and r["embed"]["vectors_usable"] and r["embed"]["fragments_to_compute"] == 0


def test_into_library_b_the_user_chooses_who_keeps_the_codes(package_a, tmp_path):
    """A default package: no recommendation, no keeper until the user chooses; the facts of both options."""
    path = workspace(str(tmp_path / "B"), "B")
    r = run(path, package_a["zip"])
    assert r["ok"], r["problems"]
    c = r["codes"]
    assert c["keeper"] is None and c["renumbered"] == "" and c["recommended"] is None
    assert c["mapping"] == {"L-00001": "L-00002", "N-00001": "N-00003"}  # above both sides
    assert c["own_documents"] == 3 and c["package_documents"] == 5 and c["collisions"] == 2
    assert c["options"] == {
        "package": {"renumbered": "own", "codes_changed": 2},
        "own": {"renumbered": "package", "codes_changed": 2},
    }
    q = r["questions"][0]
    assert [x["kind"] for x in r["questions"]] == ["codes"] and q["default"] is None and q["recommended"] is None
    assert q["options"] == ["package", "own"] and q["collisions"] == ["L-00001", "N-00001"] and "text" not in q
    kept = run(path, package_a["zip"], keep="own")["codes"]
    assert kept["keeper"] == "own" and kept["renumbered"] == "package" and kept["mapping"] == c["mapping"]
    assert run(path, package_a["zip"], keep="package")["codes"]["renumbered"] == "own"
    C.raise_high_water(os.path.join(str(tmp_path / "B"), "index"), ["N-00009"])  # a number given once is not again
    assert run(path, package_a["zip"])["codes"]["mapping"]["N-00001"] == "N-00010"


def test_into_a_copy_of_the_library_every_document_is_there(package_a, tmp_path):
    r = run(workspace(str(tmp_path / "A2"), "A"), package_a["folder"])
    same = {m["package"] for m in r["matches"]}
    assert r["ok"] and same == {"N-00001", "N-00002", "E-00001", "L-00001", "J-00001"}
    # the test cards carry no sha256 and their texts are too short for the duplicate check: alike, both stay
    assert {m["kind"] for m in r["matches"]} == {"separate"} and all(m["keep"] is None for m in r["matches"])
    assert [q["kind"] for q in r["questions"]] == ["codes"]  # no question about duplicates


def test_merges_by_the_rule():
    """classify: the same file, the same content (the higher score; a tie: the library's), another edition (the newer
    one), and the rest separate."""

    def card(desig=None, sha="", year=None):
        doc = {"year": year}
        if desig:
            doc["designation"] = {"en": desig}
        return {"doc": doc, "file": {"sha256": sha}}

    assert I.classify(card(sha="a" * 64), card(sha="a" * 64), None, 90, 10) == {
        "kind": "same_file",
        "keep": "library",
        "why": "the same file (sha256)",
    }
    assert I.classify(card(), card(), 0.95, 80, 60)["keep"] == "package"
    assert I.classify(card(), card(), 0.95, 60, 60)["keep"] == "library"  # a tie: the library's
    assert I.classify(card("GOST 1-2020"), card("GOST 1-2020"), 0.95, None, 50)["keep"] == "library"
    assert I.classify(card("GOST 1-2020"), card("GOST 2-2020"), 0.95, 90, 50)["kind"] == "separate"
    r = I.classify(card("GOST R 51858-2020"), card("GOST R 51858-2002", year=2023), None, None, None)
    assert r["kind"] == "newer_edition" and r["keep"] == "package"  # the year of the designation, not of the print
    assert I.classify(card("GOST 1510-84"), card("GOST 1510-2022"), None, None, None)["keep"] == "library"
    assert I.classify(card("GOST 1-2020"), card("GOST 1-2020"), 0.5, None, None)["kind"] == "separate"
    assert I.classify(card(), card(), 0.5, None, None) == {
        "kind": "separate",
        "keep": None,
        "why": "alike, but not the same document: both stay",
    }
    assert I.year_of(card("GOST 1510-84")) == 1984 and I.year_of(card(year=2001)) == 2001


def test_a_newer_edition_in_the_package(package_a, tmp_path):
    root = str(tmp_path / "B")
    path = workspace(root, "B")
    p = os.path.join(root, "index", "cards", "N-00001.json")
    card = C.load(p)
    card["doc"]["designation"] = {"en": "GOST R 00002-2019", "ru": "ГОСТ Р 00002-2019"}  # A's N-00002 is of 2024
    C.dump(card, p)
    r = run(path, package_a["zip"])
    m = next(m for m in r["matches"] if m["package"] == "N-00002")
    assert m["kind"] == "newer_edition" and m["keep"] == "package" and m["library"] == "N-00001"
    assert [q["kind"] for q in r["questions"]] == ["codes"]


def edited_folder(package_a, tmp_path, change):
    """A copy of the folder package with its axbase.json changed (its checksum no longer agrees)."""
    d = str(tmp_path / "pkg")
    shutil.copytree(package_a["folder"], d)
    man = json.load(open(os.path.join(d, P.MANIFEST), encoding="utf-8"))
    change(man)
    with open(os.path.join(d, P.MANIFEST), "w", encoding="utf-8") as f:
        json.dump(man, f)
    return d


def test_languages_schema_and_damage_stop_it(package_a, tmp_path):
    path = workspace(str(tmp_path / "B"), "B")
    d = edited_folder(package_a, tmp_path, lambda m: m.update(card_languages=["en"]))
    r = run(path, d, verify=False)
    assert not r["ok"] and any("no texts in ru" in p for p in r["problems"])
    r = run(path, d)
    assert any("damaged: axbase.json" in p for p in r["problems"])
    d2 = edited_folder(package_a, tmp_path / "2", lambda m: m["requires"].update(card_schema=2, app="9.0"))
    r = run(path, d2, verify=False)
    assert any("card schema 2" in p for p in r["problems"]) and any("Assistant X 9.0" in w for w in r["warnings"])
    with pytest.raises(P.PackageError):
        run(path, str(tmp_path / "none.axbase"))


def test_cards_that_do_not_pass_the_workspace(package_a, tmp_path):
    path = workspace(str(tmp_path / "B"), "B")
    with open(path, "a", encoding="utf-8") as f:  # the workspace reads German documents too
        f.write('\n[documents]\nlanguages = ["ru", "en", "de"]\n')
    r = run(path, package_a["zip"])
    assert not r["ok"] and any("no texts in de" in p for p in r["problems"])
    assert r["compatibility"]["cards_failing"] == 5


def test_a_pending_batch_long_paths_and_the_disk(package_a, tmp_path, monkeypatch):
    path = workspace(str(tmp_path / "B"), "B")
    w = settings.load(path)[0]
    write(str(w.work / "2026-10-25_batch" / "out" / "moves.json"), "[]")
    r = run(path, package_a["zip"])
    assert any("built and not applied" in p for p in r["problems"])
    write(str(w.work / "2026-10-25_batch" / "out" / "applied.json"), "{}")
    monkeypatch.setattr(I, "MAX_PATH", 20)
    monkeypatch.setattr(I, "long_paths_enabled", lambda: False)
    r = run(path, package_a["zip"])
    assert any("longest path" in p for p in r["problems"]) and r["paths"]["longest"] > 20
    monkeypatch.setattr(I, "long_paths_enabled", lambda: True)
    assert run(path, package_a["zip"])["ok"]
    monkeypatch.setattr(I.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(1, 1, 1))
    assert any("not enough disk space" in p for p in run(path, package_a["zip"])["problems"])


def test_warnings(package_a, tmp_path, monkeypatch):
    from assistant_x.core import lock

    path = workspace(str(tmp_path / "B"), "B")
    monkeypatch.setenv("OneDrive", str(tmp_path))
    held = lock.exclusive(lock.server_lock_path())
    try:
        r = run(path, package_a["zip"])
    finally:
        held.close()
    assert r["ok"]
    assert any("OneDrive" in w for w in r["warnings"]) and any("Claude holds the library" in w for w in r["warnings"])
    registry.put(os.path.join(str(tmp_path / "B"), "index"), {"id": "test-a", "version": "1.0"})
    monkeypatch.delenv("OneDrive")
    r = run(path, package_a["zip"])
    assert any("installed already" in w and "changes nothing" in w for w in r["warnings"])
    assert not any("Claude holds" in w for w in r["warnings"])


def test_the_command(package_a, tmp_path, capsys):
    from assistant_x.cli import main as cli

    path = workspace(str(tmp_path / "B"), "B")
    out = tmp_path / "report.json"
    assert cli.main(["base", "inspect", package_a["zip"], "--config", path, "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Package test-a 1.0" in text and "The install may start." in text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["codes"]["keeper"] is None and report["questions"][0]["kind"] == "codes"


def test_reference_and_default_packages(package_a, tmp_path):
    """A reference package recommends keeping its codes (and keeps them without an answer), even into a bigger
    library; a default one recommends nothing and keeps no side until the user chooses."""
    lib = package_a["library"]
    ref = str(tmp_path / "ref.axbase")
    man = X.export(load_config(lib), settings.load(lib)[1], ref, "test-a", "1.0", codes="reference", say=lambda s: None)
    assert man["codes"] == "reference"
    path = workspace(str(tmp_path / "A2"), "A")  # 6 documents against 5 of the package
    r = run(path, ref)
    c = r["codes"]
    assert c["package_codes"] == "reference" and c["recommended"] == "package" and c["keeper"] == "package"
    assert c["renumbered"] == "own" and c["options"]["package"]["codes_changed"] == c["options"]["own"]["codes_changed"] == 5
    q = next(q for q in r["questions"] if q["kind"] == "codes")
    assert q["recommended"] == "package" and q["default"] == "package" and q["package_codes"] == "reference"
    assert "reference package" in I.text(r)
    r = run(path, package_a["zip"])  # a default package: no recommendation, no side by default
    c = r["codes"]
    assert c["package_codes"] == "default" and c["recommended"] is None and c["keeper"] is None
    q = next(q for q in r["questions"] if q["kind"] == "codes")
    assert q["recommended"] is None and q["default"] is None and set(q["consequences"]) == {"package", "own"}
    assert run(path, ref, keep="own")["codes"]["keeper"] == "own"
    empty = workspace(str(tmp_path / "ws"), "empty")
    assert not [q for q in run(empty, ref)["questions"] if q["kind"] == "codes"]  # an empty workspace: no question


def test_a_number_given_once_does_not_come_back():
    """A package code at or below the mark of its letter that the library has not now was given to a document since
    removed: retired, the package document gets a new code — not for a reference package whose numbering is kept
    (reused, told), nor for the same package document that had the code before (lineage)."""
    own, pkg, high = {"N-00003": {}}, {"N-00001", "N-00002", "N-00007", "L-00001"}, {"N": 5}
    plan = I.code_plan(own, pkg, high)
    assert plan["retired"] == {"N-00001": "N-00008", "N-00002": "N-00009"} and plan["reused"] == []
    assert plan["mapping"] == {} and plan["keeper"] == "package"
    ref = I.code_plan(own, pkg, high, codes="reference")
    assert ref["retired"] == {} and ref["reused"] == ["N-00001", "N-00002"]
    assert I.code_plan(own, pkg, high, keep="own", codes="reference")["retired"] == plan["retired"]
    assert I.code_plan(own, pkg, high, lineage={"N-00001"})["retired"] == {"N-00002": "N-00008"}
    empty = I.code_plan({}, {"N-00001"}, {"N": 2})
    assert empty["retired"] == {"N-00001": "N-00003"} and empty["keeper"] == "package"
    both = I.code_plan({"N-00001": {}}, {"N-00001", "N-00002"}, {"N": 4}, keep="own")
    assert both["mapping"] == {"N-00001": "N-00005"} and both["retired"] == {"N-00002": "N-00006"}


def test_the_shingle_index_finds_what_the_comparison_with_every_text_finds():
    """ShingleIndex.best gives the pair the comparison of a package text with every library text gives, common
    shingles (boilerplate of more than COMMON texts) included, without that comparison."""
    import random

    rnd = random.Random(7)
    common = set(range(1000, 1040))  # in every text
    lib = {
        f"N-{i:05d}": common | {rnd.randrange(10_000, 60_000) for _ in range(rnd.randrange(30, 300))} for i in range(1, 120)
    }
    index = I.ShingleIndex(lib)
    assert common <= index.common
    for k in range(60):
        src = lib[rnd.choice(sorted(lib))]
        fp = set(rnd.sample(sorted(src), max(1, len(src) // rnd.choice((1, 2, 4))))) | {
            rnd.randrange(60_000, 90_000) for _ in range(rnd.randrange(0, 80))
        }
        skip = set(rnd.sample(sorted(lib), 3))
        brute = max(((len(fp & f) / len(fp), c) for c, f in lib.items() if c not in skip), default=(0, None))
        got = index.best(fp, skip, 0.30)
        assert got == brute if brute[0] >= 0.30 else got[0] < 0.30 or got == brute, (k, got, brute)
