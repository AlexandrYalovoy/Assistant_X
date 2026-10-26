# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x base install (base/install.py): the package of library A into an empty workspace, into library B (B's
colliding documents renumbered: the end state of tests/base/libraries.renumber), with --keep own (the package
renumbered), B's package into A, a second install of the same version, an install interrupted and resumed or undone,
the answers (skip, replace), a malicious zip, a pending intake batch, the marker the search server sees."""

import hashlib, json, os, shutil, zipfile

import pytest

from assistant_x.base import export as X, install as B, package as P, registry
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import connect, load_config, maintenance
from tests.base import libraries
from tests.search.conftest import build, make_library, write
from tests.search.fake_embedder import embed


def say(_):
    pass


@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    """The package of library A (built and embedded with the fake model) and the package of library B (no vectors)."""
    base = tmp_path_factory.mktemp("install")
    a = make_library(str(base / "A"))
    build(a)
    embed(a)
    X.export(load_config(a), settings.load(a)[1], str(base / "a.axbase"), "test-a", "1.0", say=say)
    b = libraries.make_b(str(base / "B"))
    build(b)
    X.export(load_config(b), settings.load(b)[1], str(base / "b.axbase"), "test-b", "1.0", say=say)
    return {"a": str(base / "a.axbase"), "b": str(base / "b.axbase")}


def state(root, originals=True):
    """{relative path: sha256} of the cards, texts and originals of a workspace (the tables aside); originals=False:
    the originals by their names only (two runs of make_b write PDFs of other bytes). Every file left in the work
    folders of the installs (.assistant_x/w) or in a nested .assistant_x counts too: a rollback leaves none."""
    out = {}
    for top in (".assistant_x/w", ".assistant_x/.assistant_x"):
        for dp, _, fns in os.walk(os.path.join(root, top)):
            for f in fns:
                out[os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/")] = "leftover"
    for top in ("index/cards", "index/texts", "library"):
        for dp, _, fns in os.walk(os.path.join(root, top)):
            for f in fns:
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, root).replace(os.sep, "/")
                out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest() if originals or top != "library" else ""
    return out


def install(config, pkg, **kw):
    return B.install(pkg, confirm=True, config=config, say=say, **kw)


def empty(root):
    write(
        os.path.join(root, "assistant_x.toml"),
        'profile = "general"\n\n[documents]\n# languages = ["ru", "en"]\nlanguages = ["en"]\n',
    )
    return os.path.join(root, "assistant_x.toml")


def test_into_an_empty_workspace(packages, tmp_path):
    root = str(tmp_path / "ws")
    path = empty(root)
    assert install(path, packages["a"]) == 0
    assert set(C.paths(os.path.join(root, "index", "cards"))) == {"N-00001", "N-00002", "E-00001", "L-00001", "J-00001"}
    card = C.load(os.path.join(root, "index", "cards", "E-00001.json"))
    assert card["intake"]["package"] == {"id": "test-a", "version": "1.0", "code": "E-00001"}
    assert os.path.exists(os.path.join(root, "library", "04_Datasheets", "E-00001_Test-Pump", "E-00001-02_Trials.pdf"))
    toml = open(path, encoding="utf-8").read()
    assert 'profile = "oil-gas-ru"' in toml and 'languages = ["ru", "en"]' in toml and "# languages" in toml
    assert registry.get(os.path.join(root, "index"), "test-a")["documents"] == 5
    cfg = load_config(path)
    con = connect(cfg["db"], readonly=True)
    assert con.execute("SELECT count(*) FROM docs WHERE parent = ''").fetchone()[0] == 5
    assert con.execute("SELECT count(*) FROM chunks WHERE vec_row IS NULL").fetchone()[0] == 0  # the package's vectors
    con.close()
    events = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    assert events.count("installed from package test-a 1.0") == 5
    assert not maintenance(cfg["index_dir"]) and not os.path.exists(
        os.path.join(root, ".assistant_x", "w", B.staging(settings.load(path)[0], "test-a").name)
    )
    assert any(f.startswith("base_install_test-a") for f in os.listdir(os.path.join(root, "reports")))
    assert any(f.endswith("-before-test-a.zip") for f in os.listdir(os.path.join(root, ".assistant_x", "backups")))
    from assistant_x.search import check_index

    assert check_index.run(cfg, quiet=True) == 0
    # the same version again: nothing to do, nothing changes
    before = state(root)
    assert install(path, packages["a"]) == 0 and state(root) == before


def test_into_library_b_its_documents_get_new_codes(packages, tmp_path):
    root, ref = str(tmp_path / "B"), str(tmp_path / "ref")
    path = libraries.make_b(root)
    libraries.make_b(ref)
    mapping = {"L-00001": "L-00002", "N-00001": "N-00003"}
    libraries.renumber(ref, mapping)  # what the documents of B must look like after the install
    assert install(path, packages["a"]) == 1  # a default package: the user has to choose
    assert install(path, packages["a"], keep="package") == 0
    cards = os.path.join(root, "index", "cards")
    assert set(C.paths(cards)) == {"N-00001", "N-00002", "E-00001", "L-00001", "J-00001", "N-00003", "L-00002", "P-00001"}
    for new in mapping.values():
        got, want = C.load(os.path.join(cards, f"{new}.json")), C.load(os.path.join(ref, "index", "cards", f"{new}.json"))
        assert got == want
        assert (
            open(os.path.join(root, "index", "texts", f"{new}.md"), encoding="utf-8").read()
            == open(os.path.join(ref, "index", "texts", f"{new}.md"), encoding="utf-8").read()
        )
        assert os.path.exists(os.path.join(root, *got["file"]["library"].split("/")))
    assert C.load(os.path.join(cards, "N-00001.json"))["intake"]["package"]["id"] == "test-a"
    events = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    assert "renumbered: N-00001 -> N-00003" in events and "renumbered: L-00001 -> L-00002" in events
    assert C.high_water(os.path.join(root, "index")) == {"E": 1, "J": 1, "L": 2, "N": 3, "P": 1}
    rows = {
        r["code"]
        for r in __import__("assistant_x.intake.manifest", fromlist=["load"])
        .load(__import__("pathlib").Path(root) / "index" / "manifest.tsv")
        .values()
    }
    assert {"N-00003", "L-00002", "N-00001", "E-00001-02"} <= rows


def test_keep_own_renumbers_the_package(packages, tmp_path):
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    before = state(root)
    assert install(path, packages["a"], keep="own") == 0
    after = state(root)
    assert all(after.get(k) == v for k, v in before.items() if k.startswith(("library/", "index/texts/")))
    card = C.load(os.path.join(root, "index", "cards", "N-00003.json"))
    assert card["intake"]["package"]["code"] == "N-00001" and "Test-Well-Rate" in card["file"]["library"]
    assert C.load(os.path.join(root, "index", "cards", "N-00001.json"))["doc"]["title"]["en"].startswith("Package standard")


def test_the_package_of_b_into_library_a(packages, tmp_path):
    root = str(tmp_path / "A")
    path = make_library(root)
    assert install(path, packages["b"], keep="own") == 0  # appended after A's numbering: B's package renumbered
    cards = os.path.join(root, "index", "cards")
    assert C.load(os.path.join(cards, "N-00003.json"))["intake"]["package"] == {
        "id": "test-b",
        "version": "1.0",
        "code": "N-00001",
    }
    assert C.load(os.path.join(cards, "L-00002.json"))["intake"]["package"]["code"] == "L-00001"
    assert C.load(os.path.join(cards, "P-00001.json"))["intake"]["package"]["code"] == "P-00001"
    assert "Test-Well-Rate" in C.load(os.path.join(cards, "N-00001.json"))["file"]["library"]


def test_a_newer_edition_wins_and_takes_the_users_code(packages, tmp_path):
    """B's N-00001 is GOST R 00002-2019, the package's N-00002 is its 2024 edition: the package's stays and, since B
    keeps its numbering (keep own), takes the code N-00001; B's goes to inbox\\_to_delete\\merged_<date>; the
    package's N-00001 gets a new code (N-00001 is taken by the winner)."""
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    p = os.path.join(root, "index", "cards", "N-00001.json")
    card = C.load(p)
    card["doc"]["designation"] = {"en": "GOST R 00002-2019", "ru": "ГОСТ Р 00002-2019"}
    C.dump(card, p)
    assert install(path, packages["a"], keep="own") == 0
    cards = os.path.join(root, "index", "cards")
    won = C.load(os.path.join(cards, "N-00001.json"))
    assert won["intake"]["package"]["code"] == "N-00002" and "Test-Separator" in won["file"]["library"]
    assert C.load(os.path.join(cards, "N-00003.json"))["intake"]["package"]["code"] == "N-00001"
    assert C.load(os.path.join(cards, "L-00002.json"))["intake"]["package"]["code"] == "L-00001"
    assert C.load(os.path.join(cards, "L-00001.json")).get("intake", {}).get("package") is None  # B's own
    merged = [os.path.join(dp, f) for dp, _, fns in os.walk(os.path.join(root, "inbox", "_to_delete")) for f in fns]
    assert any(f.endswith("N-00001_Package-Pipeline-Standard.pdf") for f in merged)  # never deleted
    assert any(f.endswith(os.path.join("cards", "N-00001.json")) for f in merged)
    events = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    assert "merged (newer_edition)" in events
    report = [f for f in os.listdir(os.path.join(root, "reports")) if f.startswith("base_install_")]
    text = open(os.path.join(root, "reports", report[0]), encoding="utf-8").read()
    assert "newer_edition: kept N-00002 (package), moved N-00001" in text


def test_the_same_content_keeps_the_better_recognition(tmp_path):
    """The same long text in A's L-00001 (score 42 in A) and in B's L-00001 (no score): the package's stays, B's
    goes to merged_<date>; B is renumbered nowhere, the freed code goes to the package's document."""
    words = " ".join(f"pump{i} seal{i} shaft{i} bearing{i}" for i in range(400))
    a = str(tmp_path / "A")
    path_a = make_library(a)
    write(os.path.join(a, "index", "texts", "L-00001.md"), f"=== page 1 ===\n\n{words}\n\n")
    build(path_a)
    pkg = str(tmp_path / "a.axbase")
    X.export(load_config(path_a), settings.load(path_a)[1], pkg, "test-a", "1.0", vectors=False, say=say)
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    write(os.path.join(root, "index", "texts", "L-00001.md"), f"=== page 1 ===\n\n{words}\n\n=== page 2 ===\n\nx\n\n")
    assert install(path, pkg, keep="package") == 0
    card = C.load(os.path.join(root, "index", "cards", "L-00001.json"))
    assert card["intake"]["package"]["code"] == "L-00001"
    assert not os.path.exists(os.path.join(root, "index", "cards", "L-00002.json"))  # nobody renumbered for it
    merged = [f for _, _, fns in os.walk(os.path.join(root, "inbox", "_to_delete")) for f in fns]
    assert "L-00001_Package-Pump-Handbook.pdf" in merged


@pytest.mark.parametrize("fail", ["renames two", "place", "base"])
def test_interrupted_and_rolled_back(packages, tmp_path, monkeypatch, fail):
    from assistant_x.intake import manifest

    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    manifest.main(["--root", root])
    before = state(root)
    tables = {f: open(os.path.join(root, "index", f), encoding="utf-8").read() for f in ("manifest.tsv", "CATALOG.md")}
    real = B.run_moves

    def moves(jr, key, todo, root_):  # one move of the step done, then the PC goes off
        if (fail, key) in (("renames two", "two_done"), ("place", "placed_done")):
            real(jr, key, todo[:1], root_)
            raise B.Stop("the PC was switched off")
        return real(jr, key, todo, root_)

    def base(*a, **kw):
        raise B.Stop("the PC was switched off")

    monkeypatch.setattr(B, "run_moves", moves)
    monkeypatch.setattr(B, "build_base", base if fail == "base" else B.build_base)
    assert install(path, packages["a"], keep="package") == 1
    monkeypatch.undo()
    assert B.install(packages["a"], rollback=True, config=path, say=say) == 0
    assert state(root) == before
    for f, text in tables.items():
        assert open(os.path.join(root, "index", f), encoding="utf-8").read() == text
    assert not maintenance(load_config(path)["index_dir"]) and registry.load(os.path.join(root, "index")) == []
    assert install(path, packages["a"], keep="package") == 0  # and it installs afterwards


def malicious(path, name, data=b"x", compress=zipfile.ZIP_STORED, link=False):
    """A copy of a package with one more entry."""
    out = str(path)
    with zipfile.ZipFile(out, "a") as z:
        info = zipfile.ZipInfo(name)
        info.compress_type = compress
        if link:
            info.external_attr = 0o120777 << 16
        z.writestr(info, data)
    return out


@pytest.mark.parametrize(
    "name,kw",
    [
        ("../evil.txt", {}),
        ("library/../../evil.txt", {}),
        ("/abs.txt", {}),
        ("C:/abs.txt", {}),
        ("library/CON.txt", {}),
        ("library/a.pdf.", {}),
        ("library/a:b.pdf", {}),
        ("library/x.pdf", {"link": True}),
        ("library/y.pdf", {"compress": zipfile.ZIP_DEFLATED}),
        ("CARDS/N-00001.json", {}),
        ("evil.exe", {}),
    ],
)
def test_a_malicious_package_changes_nothing(packages, tmp_path, name, kw):
    pkg = tmp_path / "bad.axbase"
    shutil.copyfile(packages["a"], pkg)
    malicious(pkg, name, **kw)
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    before = state(root)
    with P.Package(pkg) as p:
        assert B.check_entries(p) or kw.get("link") is None and B.bad_name(name), name  # refused by its name or kind
    from assistant_x.base import inspection as I

    report = I.inspect(load_config(path), settings.load(path)[1], str(pkg), verify=False)  # inspect says it already
    assert not report["ok"] and any(x.startswith("package entry ") for x in report["problems"]), report["problems"]
    assert install(path, str(pkg)) == 1
    assert state(root) == before and not os.path.exists(os.path.join(root, ".assistant_x", "w"))
    assert not os.path.exists(os.path.join(tmp_path, "evil.txt"))


def test_a_damaged_package_is_refused_cleanly(packages, tmp_path, capsys):
    """One byte of a stored entry changed (a bad CRC, as a cut or damaged download gives): inspect and install say
    "damaged" with the name of the entry, no traceback, nothing changes."""
    from assistant_x.base import inspection as I

    pkg = tmp_path / "damaged.axbase"
    shutil.copyfile(packages["a"], pkg)
    with zipfile.ZipFile(pkg) as z:
        info = next(i for i in z.infolist() if i.filename.startswith("texts/") and i.file_size > 100)
    data = bytearray(pkg.read_bytes())
    at = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 10
    data[at] ^= 0xFF
    pkg.write_bytes(bytes(data))
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    before = state(root)
    report = I.inspect(load_config(path), settings.load(path)[1], str(pkg))
    assert not report["ok"] and any(f"damaged: {info.filename}" in x for x in report["problems"])
    assert I.main([str(pkg), "--config", path]) == 1 and "damaged" in capsys.readouterr().out
    assert install(path, str(pkg)) == 1 and state(root) == before


def test_names_of_a_package():
    assert B.bad_name("cards/N-00001.json") == "" and B.bad_name("library/01_Standards/N-00001_x.pdf") == ""
    assert B.bad_name("library/nul") and B.bad_name("library/com1.pdf") and B.bad_name("library/e\u0301.pdf")


def test_a_pending_batch_stops_it(packages, tmp_path):
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    write(os.path.join(root, ".assistant_x", "work", "batch", "out", "moves.json"), "[]")
    before = state(root)
    assert install(path, packages["a"]) == 1 and state(root) == before


def test_without_confirm_it_only_tells(packages, tmp_path, capsys):
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    before = state(root)
    assert B.install(packages["a"], config=path) == 0 and state(root) == before
    assert "--confirm" in capsys.readouterr().out


def test_the_marker_of_the_server(tmp_path):
    from assistant_x.core.common import clear_maintenance, maintenance_note, set_maintenance

    set_maintenance(str(tmp_path), "install of x")
    m = maintenance(str(tmp_path))
    assert m["pid"] == os.getpid() and "being changed" in maintenance_note(m)
    data = json.load(open(tmp_path / "maintenance.json", encoding="utf-8"))
    data["pid"] = 999_999_99  # a process that is gone: the note counts for nothing
    json.dump(data, open(tmp_path / "maintenance.json", "w", encoding="utf-8"))
    assert maintenance(str(tmp_path)) is None
    clear_maintenance(str(tmp_path))
    assert not (tmp_path / "maintenance.json").exists()


def test_page_image_while_installing(packages, tmp_path, monkeypatch):
    from assistant_x.core.common import set_maintenance
    from assistant_x.server import mcp_server

    root = str(tmp_path / "ws")
    path = empty(root)
    assert install(path, packages["a"]) == 0
    from assistant_x.search.retrieval import Library

    monkeypatch.setattr(mcp_server, "_lib", Library(load_config(path)))
    set_maintenance(load_config(path)["index_dir"], "install of test")
    assert "being changed" in mcp_server.page_image("N-00001", 1)


def test_a_reference_package_keeps_its_codes_and_the_answer_decides(tmp_path):
    """Into library A (6 documents) the reference package of B (3) keeps its codes when no one answers; the answer
    "own" of the question of the codes appends it after A's numbering instead."""
    b = libraries.make_b(str(tmp_path / "srcB"))
    build(b)
    ref = str(tmp_path / "b-ref.axbase")
    X.export(load_config(b), settings.load(b)[1], ref, "test-b", "1.0", codes="reference", say=say)
    root = str(tmp_path / "A")
    path = make_library(root)
    assert install(path, ref) == 0
    cards = os.path.join(root, "index", "cards")
    assert C.load(os.path.join(cards, "N-00001.json"))["intake"]["package"]["id"] == "test-b"
    assert "Test-Well-Rate" in C.load(os.path.join(cards, "N-00003.json"))["file"]["library"]  # A's, renumbered
    root2 = str(tmp_path / "A2")
    path2 = make_library(root2)
    assert install(path2, ref, answers={"codes": "own"}) == 0
    cards = os.path.join(root2, "index", "cards")
    assert "Test-Well-Rate" in C.load(os.path.join(cards, "N-00001.json"))["file"]["library"]  # A keeps its codes
    assert C.load(os.path.join(cards, "N-00003.json"))["intake"]["package"]["code"] == "N-00001"


def test_a_default_package_needs_the_choice(packages, tmp_path, capsys):
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    before = state(root)
    assert B.install(packages["a"], confirm=True, config=path) == 1 and state(root) == before
    assert "--keep package" in capsys.readouterr().out
    assert install(path, packages["a"], answers={"codes": "own"}) == 0  # the answer of the question is the choice
    assert C.load(os.path.join(root, "index", "cards", "N-00003.json"))["intake"]["package"]["code"] == "N-00001"


def test_a_failed_build_stops_the_install_before_embed(packages, tmp_path, monkeypatch):
    """build fails inside the install: no embed on that base, the install stops with its journal (resume or
    rollback), the marker of the server is gone; a base without its meta table gives embed a clear message."""
    from assistant_x.search import build_index, embed as E

    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    monkeypatch.setattr(build_index, "main", lambda: 2)
    monkeypatch.setattr(E, "main", lambda: (_ for _ in ()).throw(AssertionError("embed after a failed build")))
    assert install(path, packages["a"], keep="package") == 1
    cfg = load_config(path)
    assert not maintenance(cfg["index_dir"])
    jr = B.Journal(B.staging(settings.load(path)[0], "test-a") / B.JOURNAL)
    assert "place" in jr.data["steps"] and "base" not in jr.data["steps"]
    monkeypatch.undo()
    assert B.install(packages["a"], rollback=True, config=path, say=say) == 0


def test_embed_on_a_base_that_is_not_built(tmp_path):
    import sqlite3
    from assistant_x.core.common import vectors_path
    from assistant_x.search import embed as E

    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    cfg = load_config(path)
    os.makedirs(os.path.dirname(cfg["db"]), exist_ok=True)
    con = sqlite3.connect(cfg["db"])
    con.execute("CREATE TABLE docs(code TEXT)")
    con.commit()
    assert vectors_path(cfg, con) == cfg["vectors"]
    con.close()
    import sys

    argv, sys.argv = sys.argv, ["embed.py", "--config", path]
    try:
        with pytest.raises(SystemExit, match="not built"):
            E.main()
    finally:
        sys.argv = argv


def test_a_number_given_once_is_not_given_to_a_package_document(packages, tmp_path):
    """The library once had N-00001 … N-00009 (removed since): the package's N-00001 and N-00002 get new codes, the
    report and the events say so; the same package removed and installed again keeps its codes (lineage)."""
    root = str(tmp_path / "ws")
    path = empty(root)
    C.raise_high_water(os.path.join(root, "index"), ["N-00009"])
    assert install(path, packages["a"]) == 0
    cards = os.path.join(root, "index", "cards")
    assert {"N-00010", "N-00011"} <= set(C.paths(cards)) and "N-00001" not in C.paths(cards)
    assert C.load(os.path.join(cards, "N-00010.json"))["intake"]["package"]["code"] == "N-00001"
    events = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    assert "its code there N-00001" in events
    report = [f for f in os.listdir(os.path.join(root, "reports")) if f.startswith("base_install_")]
    assert "N-00001 -> N-00010" in open(os.path.join(root, "reports", report[0]), encoding="utf-8").read()
    root2 = str(tmp_path / "ws2")
    path2 = empty(root2)
    assert install(path2, packages["a"]) == 0
    from assistant_x.base import update as U

    assert U.remove("test-a", confirm=True, config=path2, say=say) == 0
    assert install(path2, packages["a"]) == 0
    assert {"N-00001", "N-00002", "E-00001"} <= set(C.paths(os.path.join(root2, "index", "cards")))


def test_resume_and_rollback_take_the_same_package(packages, tmp_path, monkeypatch):
    """An interrupted install goes on (or is undone) only with the package it started with: another file of the same
    id and version (made again, so another manifest and checksums) is refused and nothing changes."""
    other = str(tmp_path / "a-again.axbase")
    a = make_library(str(tmp_path / "A"))
    build(a)
    X.export(load_config(a), settings.load(a)[1], other, "test-a", "1.0", vectors=False, say=say)
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    real = B.run_moves

    def moves(jr, key, todo, root_):
        if key == "placed_done":
            real(jr, key, todo[:1], root_)
            raise B.Stop("the PC was switched off")
        return real(jr, key, todo, root_)

    monkeypatch.setattr(B, "run_moves", moves)
    assert install(path, packages["a"], keep="package") == 1
    monkeypatch.undo()
    jr = B.Journal(B.staging(settings.load(path)[0], "test-a") / B.JOURNAL)
    before = (state(root), dict(jr.data))
    out = []
    assert B.install(other, resume=True, config=path, say=out.append) == 1
    assert B.install(other, rollback=True, config=path, say=out.append) == 1
    assert all("not the package" in x for x in out)
    jr = B.Journal(B.staging(settings.load(path)[0], "test-a") / B.JOURNAL)
    assert (state(root), dict(jr.data)) == before
    assert B.install(packages["a"], resume=True, config=path, say=say) == 0


def test_no_intake_while_an_install_is_open_and_its_rollback_keeps_other_cards(packages, tmp_path, monkeypatch, capsys):
    """An interrupted install keeps the intake from building or applying (its rollback restores the cards of that
    moment); the rollback removes only the cards the install made, never one made by someone else since."""
    from assistant_x.intake import apply as intake_apply, build as intake_build, config as intake_cfg

    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    real = B.run_moves

    def moves(jr, key, todo, root_):
        if key == "placed_done":
            real(jr, key, todo, root_)
            raise B.Stop("the PC was switched off")
        return real(jr, key, todo, root_)

    monkeypatch.setattr(B, "run_moves", moves)
    assert install(path, packages["a"], keep="package") == 1
    monkeypatch.undo()
    cfg = intake_cfg.load(path)
    work = os.path.join(root, ".assistant_x", "work", "batch")
    os.makedirs(work, exist_ok=True)
    assert intake_build.build(cfg, work) == 1 and intake_apply.apply(cfg, work) == 1
    assert capsys.readouterr().out.count("install of test-a 1.0 was interrupted") == 2
    card = C.load(os.path.join(root, "index", "cards", "P-00001.json"))
    card["code"] = "P-00007"
    C.dump(card, os.path.join(root, "index", "cards", "P-00007.json"))  # made by hand meanwhile
    assert B.install(packages["a"], rollback=True, config=path, say=say) == 0
    cards = set(C.paths(os.path.join(root, "index", "cards")))
    assert cards == {"N-00001", "L-00001", "P-00001", "P-00007"}


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        b"[1, 2]",
        b"{not json",
        json.dumps({"format": "axbase/9"}).encode(),
        json.dumps({"format": "axbase/1"}).encode(),
    ],
)
def test_a_refused_package_lets_its_file_go(tmp_path, monkeypatch, manifest):
    """Every refusal of Package() closes the zip it opened, not only the garbage collector later: the file can be
    moved or deleted at once (Windows refuses an open one)."""
    path = tmp_path / "refused.axbase"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("README.txt", "x")
        if manifest is not None:
            z.writestr(P.MANIFEST, manifest)
    opened = []

    class Kept(zipfile.ZipFile):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)  # a reference of the test: the collector cannot close it

    monkeypatch.setattr(P.zipfile, "ZipFile", Kept)
    with pytest.raises(P.PackageError):
        P.Package(str(path))
    assert opened and all(z.fp is None for z in opened)
    os.remove(path)


def test_a_rollback_removes_only_the_folders_it_made(packages, tmp_path, monkeypatch):
    """The user's empty folders in library (a shelf not used yet, a folder made by hand) stay after a rollback; the
    folders the interrupted install made are gone."""
    root = str(tmp_path / "B")
    path = libraries.make_b(root)
    mine = [os.path.join(root, "library", "07_Empty_shelf"), os.path.join(root, "library", "01_Standards", "my folder")]
    for d in mine:
        os.makedirs(d)

    def folders():
        return {dp for dp, _, _ in os.walk(os.path.join(root, "library"))}

    before = folders()

    def base(*a, **kw):
        raise B.Stop("the PC was switched off")

    monkeypatch.setattr(B, "build_base", base)
    assert install(path, packages["a"], keep="package") == 1
    made = folders() - before
    assert made  # the documents of the package went into new folders
    jr = B.Journal(B.staging(settings.load(path)[0], "test-a") / B.JOURNAL)
    assert jr.data["made_dirs"]  # noted in the journal of the install
    monkeypatch.undo()
    assert B.install(packages["a"], rollback=True, config=path, say=say) == 0
    assert all(os.path.isdir(d) for d in mine) and folders() == before
