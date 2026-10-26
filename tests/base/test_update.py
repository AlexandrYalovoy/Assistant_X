# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x base update and base remove (base/update.py): version 2 of the package of library A over library B
with version 1 installed — a document changed, one removed, one new whose package code is taken here (a local code),
the rest the same; the user's documents never change; the plan without --confirm; an update interrupted and undone;
the removal of the package."""

import json, os, shutil

import pytest

from assistant_x.base import export as X, install as B, registry, update as U
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import load_config
from tests.base import libraries
from tests.base.test_install import state
from tests.search.conftest import build, make_library, write
from tests.search.fake_embedder import embed


def say(_):
    pass


@pytest.fixture(scope="module")
def versions(tmp_path_factory):
    """Version 1.0 and 2.0 of the package of library A: in 2.0 N-00002 has another text, J-00001 is gone and
    P-00001 (a report taken from library B) is new."""
    base = tmp_path_factory.mktemp("update")
    root = str(base / "A")
    a = make_library(root)
    build(a)
    embed(a)
    X.export(load_config(a), settings.load(a)[1], str(base / "v1.axbase"), "test-a", "1.0", say=say)
    write(
        os.path.join(root, "index", "texts", "N-00002.md"),
        "=== page 1 ===\n\n# 1. Separators\n\nThe 2026 edition: the gas velocity is checked at the inlet too.\n\n",
    )
    for p in (
        os.path.join(root, "index", "cards", "J-00001.json"),
        os.path.join(root, "index", "texts", "J-00001.md"),
        os.path.join(root, "library", "06_Journals", "J-00001_Test-Journal-Issue.pdf"),
    ):
        os.remove(p)
    src = str(base / "srcB")
    libraries.make_b(src)
    shutil.copyfile(
        os.path.join(src, "index", "cards", "P-00001.json"), os.path.join(root, "index", "cards", "P-00001.json")
    )
    shutil.copyfile(os.path.join(src, "index", "texts", "P-00001.md"), os.path.join(root, "index", "texts", "P-00001.md"))
    os.makedirs(os.path.join(root, "library", "03_Projects"), exist_ok=True)
    shutil.copyfile(
        os.path.join(src, "library", "03_Projects", "P-00001_Package-Gas-Plant-Report.pdf"),
        os.path.join(root, "library", "03_Projects", "P-00001_Package-Gas-Plant-Report.pdf"),
    )
    p = os.path.join(root, "index", "cards", "P-00001.json")
    card = C.load(p)
    card["intake"].pop("package", None)
    C.dump(card, p)
    from assistant_x.search import catalog

    catalog.write(os.path.join(root, "index"), "2026-10-25", {"profile": "oil-gas-ru"})
    build(a)
    X.export(load_config(a), settings.load(a)[1], str(base / "v2.axbase"), "test-a", "2.0", say=say)
    return {"v1": str(base / "v1.axbase"), "v2": str(base / "v2.axbase")}


def installed_b(root, v1):
    """Library B with version 1.0 installed (the package keeps its codes: B's N-00001, L-00001 renumbered)."""
    path = libraries.make_b(root)
    assert B.install(v1, confirm=True, keep="package", config=path, say=say) == 0
    return path


def own_state(root):
    """The files of the user's own documents of B (after the install: N-00003, L-00002, P-00001)."""
    return {k: v for k, v in state(root).items() if any(c in k for c in ("N-00003", "L-00002", "P-00001"))}


def test_an_update(versions, tmp_path):
    root = str(tmp_path / "B")
    path = installed_b(root, versions["v1"])
    own = own_state(root)
    cards = os.path.join(root, "index", "cards")
    assert U.update(versions["v2"], config=path, say=say) == 0  # the plan only
    assert registry.get(os.path.join(root, "index"), "test-a")["version"] == "1.0"
    assert U.update(versions["v2"], confirm=True, config=path, say=say) == 0
    assert own_state(root) == own  # the user's documents: not one byte changed, none renumbered
    assert "2026 edition" in open(os.path.join(root, "index", "texts", "N-00002.md"), encoding="utf-8").read()
    assert not os.path.exists(os.path.join(cards, "J-00001.json"))
    removed = os.path.join(root, "inbox", "_to_delete")
    assert any("J-00001" in f for _, _, fns in os.walk(removed) for f in fns)
    assert any("N-00002" in f for _, _, fns in os.walk(removed) for f in fns)  # the old version of the changed one
    new = C.load(os.path.join(cards, "P-00002.json"))  # P-00001 is the user's: the new document gets a local code
    assert new["intake"]["package"] == {"id": "test-a", "version": "2.0", "code": "P-00001"}
    assert C.load(os.path.join(cards, "E-00001.json"))["intake"]["package"]["version"] == "2.0"
    assert C.load(os.path.join(cards, "P-00001.json")).get("intake", {}).get("package") is None
    assert registry.get(os.path.join(root, "index"), "test-a")["version"] == "2.0"
    events = open(os.path.join(root, "index", "intake_events.tsv"), encoding="utf-8").read()
    assert "updated from package test-a 2.0" in events and "no longer in package test-a 2.0" in events
    assert C.high_water(os.path.join(root, "index"))["J"] == 1  # J-00001 is never given again
    from assistant_x.search import check_index

    assert check_index.run(load_config(path), quiet=True) == 0
    assert U.update(versions["v2"], confirm=True, config=path, say=say) == 0  # the same version: nothing to do


def test_update_of_a_package_not_installed(versions, tmp_path):
    path = libraries.make_b(str(tmp_path / "B"))
    assert U.update(versions["v2"], confirm=True, config=path, say=say) == 1


def test_an_update_interrupted_and_undone(versions, tmp_path, monkeypatch):
    root = str(tmp_path / "B")
    path = installed_b(root, versions["v1"])
    before = state(root)
    real = B.run_moves

    def moves(jr, key, todo, root_):
        if key == "placed_done":
            real(jr, key, todo[:1], root_)
            raise B.Stop("the PC was switched off")
        return real(jr, key, todo, root_)

    monkeypatch.setattr(B, "run_moves", moves)
    assert U.update(versions["v2"], confirm=True, config=path, say=say) == 1
    monkeypatch.undo()
    assert B.install(versions["v2"], confirm=True, config=path, say=say) == 1  # an update is to finish first
    assert U.update(versions["v2"], rollback=True, config=path, say=say) == 0
    assert state(root) == before
    assert registry.get(os.path.join(root, "index"), "test-a")["version"] == "1.0"


def test_remove(versions, tmp_path):
    root = str(tmp_path / "B")
    path = installed_b(root, versions["v1"])
    own = own_state(root)
    assert U.remove("test-a", config=path, say=say) == 0  # the plan only
    assert registry.get(os.path.join(root, "index"), "test-a")
    assert U.remove("test-a", confirm=True, config=path, say=say) == 0
    assert set(C.paths(os.path.join(root, "index", "cards"))) == {"N-00003", "L-00002", "P-00001"}
    assert own_state(root) == own and registry.load(os.path.join(root, "index")) == []
    assert C.high_water(os.path.join(root, "index"))["E"] == 1
    assert U.remove("test-a", confirm=True, config=path, say=say) == 1  # not installed any more


def test_the_commands(versions, tmp_path, capsys):
    from assistant_x.cli import main as cli

    root = str(tmp_path / "B")
    path = installed_b(root, versions["v1"])
    assert cli.main(["base", "update", versions["v2"], "--config", path]) == 0
    assert "Update of test-a 1.0 -> 2.0" in capsys.readouterr().out
    assert cli.main(["base", "remove", "test-a", "--config", path]) == 0
    assert "Removal of test-a" in capsys.readouterr().out
    assert json.loads(open(os.path.join(root, "index", "packages.json"), encoding="utf-8").read())["packages"]


def test_the_plan_of_an_update_extracts_nothing(versions, tmp_path, capsys):
    """Without --confirm the plan is read from the package where it lies: no work folder, no journal; it is the plan
    of the extracted package."""
    from assistant_x.base import package as P

    root = str(tmp_path / "B")
    path = installed_b(root, versions["v1"])
    capsys.readouterr()
    assert U.update(versions["v2"], config=path, say=print) == 0
    out = capsys.readouterr().out
    assert "unchanged" in out and "--confirm" in out
    w = settings.load(path)[0]
    assert not os.path.exists(B.staging(w, "test-a"))
    from pathlib import Path

    with P.Package(versions["v2"]) as pkg:
        B.extract(pkg, str(tmp_path / "x"))
    assert U.plan_of_package(w, versions["v2"], "test-a") == U.plan_update(w, Path(tmp_path / "x"), "test-a")
