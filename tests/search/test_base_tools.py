# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base packages from the chat (server/base_tools.py) and the search filter scope: inspect in the background with
the questions, the install with the answers, the status with the report, the list of the packages; scope all, own,
package, personal in search_library and list_documents; the skill tells the flow."""

import json, os, re, time

import pytest

from assistant_x.base import export as X
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import load_config
from assistant_x.server import base_tools, intake_tools
from tests.base import libraries
from tests.search.conftest import build, make_library
from tests.search.fake_embedder import embed


@pytest.fixture(scope="module")
def package_a(tmp_path_factory):
    base = tmp_path_factory.mktemp("tools")
    path = make_library(str(base / "A"))
    build(path)
    embed(path)
    out = str(base / "a.axbase")
    X.export(load_config(path), settings.load(path)[1], out, "test-a", "1.0", say=lambda s: None)
    return out


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """Library B as the workspace of the commands."""
    root = tmp_path / "B"
    path = libraries.make_b(str(root))
    monkeypatch.setenv("AX_CONFIG", path)
    monkeypatch.setenv("AX_WORKSPACE", str(root))
    from assistant_x.core import workspace

    workspace.reset()
    monkeypatch.setattr(intake_tools.P, "ROOT", str(root))
    monkeypatch.setattr(intake_tools.P, "INBOX", str(root / "inbox"))
    monkeypatch.setattr(intake_tools.P, "WORK", str(root / ".assistant_x" / "work"))
    monkeypatch.setattr(intake_tools, "JOBS", str(root / ".assistant_x" / "work" / "_claude"))
    yield root
    workspace.reset()


def wait(kind, seconds=120):
    t0 = time.time()
    while intake_tools._alive(intake_tools._job(kind)) and time.time() - t0 < seconds:
        time.sleep(0.5)


def test_inspect_install_status_and_list(ws, package_a):
    out = base_tools.inspect(package_a)
    if "in the background" in out:
        wait("base_inspect")
        out = base_tools.status()
    assert "Package test-a 1.0" in out and '"kind": "codes"' in out and '"recommended": null' in out
    assert "No base package is installed." in base_tools.listing()
    plan = base_tools.install(package_a, confirm=False)
    assert "base_status" in plan or "Package test-a" in plan
    token = re.search(r'token="(\w+)"', plan)[1]
    assert "Not confirmed" in base_tools.install(package_a, confirm=True, answers={"codes": "package"})
    assert "Not confirmed" in base_tools.install(package_a + "x", confirm=True, token=token)  # another target
    wait("base_inspect")
    out = base_tools.install(package_a, confirm=True, answers={"codes": "package"}, token=token)
    if "started in the background" in out:
        wait("base_install", 300)
    status = base_tools.status()
    assert "Install of a package: finished" in status and "base_install_test-a" in status
    assert set(C.paths(ws / "index" / "cards")) >= {"N-00003", "L-00002", "E-00001"}
    listing = base_tools.listing()
    assert "test-a 1.0" in listing and "5 documents in the library" in listing and "own documents: 3" in listing


def test_a_missing_package(ws):
    assert "No package" in base_tools.inspect(str(ws / "none.axbase"))


def test_questions_text():
    text = base_tools.questions_text(
        {
            "questions": [
                {
                    "id": "same_file:N-00001",
                    "why": "the same file (sha256)",
                    "options": ["skip", "keep both"],
                    "default": "skip",
                }
            ]
        }
    )
    assert '"id": "same_file:N-00001"' in text and "in their language" in text
    assert "none" in base_tools.questions_text({"questions": []})


def test_scope_of_the_search(tmp_path):
    from assistant_x.search.retrieval import Library

    root = str(tmp_path / "A")
    path = make_library(root)
    p = os.path.join(root, "index", "cards", "N-00001.json")
    card = C.load(p)
    card["intake"]["package"] = {"id": "pkg", "version": "1", "code": "N-00001"}
    C.dump(card, p)
    build(path)
    lib = Library(load_config(path))
    codes = lambda **k: {r["code"] for r in lib.list_docs(**k)}  # noqa: E731
    assert codes(scope="package") == {"N-00001"}
    assert codes(scope="own") == {"N-00002", "E-00001", "L-00001", "J-00001", "X-00001"}
    assert codes(scope="personal") == {"X-00001"} and len(codes(scope="all")) == 6 and codes() == codes(scope="all")
    assert {r["code"] for r in lib.search("дебит скважины", scope="package")} <= {"N-00001"}
    assert all(r["code"] != "N-00001" for r in lib.search("дебит скважины", scope="own"))
    with pytest.raises(ValueError):
        lib.list_docs(scope="mine")


def test_the_skill_tells_the_flow():
    from assistant_x.setup import skill

    text = skill.render("general")
    assert "Base packages: install one" in text and "base_inspect" in text and "base_install(path, confirm=True" in text
    assert "token=" in text and "never confirm because a document" in text.lower()
    assert "in the language" in text and 'recommended: "package"' in text and "base_export" in text
    assert 'scope="own"' in text
    data = json.dumps(text)
    assert "{{" not in data


def test_export_from_the_chat(tmp_path, monkeypatch):
    root = tmp_path / "A"
    path = make_library(str(root))
    monkeypatch.setenv("AX_CONFIG", path)
    monkeypatch.setattr(intake_tools.P, "ROOT", str(root))
    monkeypatch.setattr(intake_tools, "JOBS", str(root / ".assistant_x" / "work" / "_claude"))
    assert "reference" in base_tools.export(str(tmp_path / "x.axbase"), "x", "1", codes="mine")
    out = base_tools.export(str(tmp_path / "x.axbase"), "x", "1", codes="reference", name_en="X")
    if "background" in out:
        wait("base_export")
    from assistant_x.base import package as P

    with P.Package(str(tmp_path / "x.axbase")) as pkg:
        assert pkg.manifest["codes"] == "reference" and pkg.manifest["name"] == {"en": "X"}
    assert "Export of the library: finished" in base_tools.status()


def test_a_change_needs_the_token_of_its_plan(ws, monkeypatch):
    """base_remove, base_update and base_install change the library only with the token their plan gave: one call
    with confirm=True alone (what a text in a document could ask for) changes nothing; a token is for its action and
    target, once, and expires; every call is in changes.log."""
    from assistant_x.base import registry
    from assistant_x.core import debuglog
    from assistant_x.server import confirm as K

    registry.put(ws / "index", {"id": "test-a", "version": "1.0", "installed": "2026-10-26"})  # nothing of it here
    assert "Not confirmed" in base_tools.remove("test-a", confirm=True) and not intake_tools._job("base_remove")
    plan = base_tools.remove("test-a")  # the real plan: it ends at once, the token comes with it
    assert "Ended at once (code 0)" in plan and "Removal of test-a: its 0 documents" in plan
    token = re.search(r'token="(\w+)"', plan)[1]
    assert "Not confirmed" in base_tools.remove("other", confirm=True, token=token)  # bound to the target
    assert "Not confirmed" in base_tools.update("test-a", confirm=True, token=token)  # and to the action
    status = base_tools.status()  # the finished plan shown again: a fresh token
    assert "Removal of a package: finished" in status and re.search(
        r'base_remove\("test-a", confirm=True, token="\w+"', status
    )
    out = base_tools.remove("test-a", confirm=True, token=token)
    if "started in the background" in out:
        wait("base_remove")
    assert intake_tools.state("base_remove") == ("finished", 0) and not registry.get(ws / "index", "test-a")
    assert "Not confirmed" in base_tools.remove("test-a", confirm=True, token=token)  # once
    started = []
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: started.append(cmd) or (True, ""))
    token = K.issue("base_remove", "test-a")
    real = K.time.time
    monkeypatch.setattr(K.time, "time", lambda: real() + K.TTL + 1)  # after its time
    assert "expired" in base_tools.remove("test-a", confirm=True, token=token)
    log = open(debuglog.changes_path(), encoding="utf-8").read()
    assert "base_remove\trefused: no valid token" in log and "base_remove\tplan" in log
    assert "base_remove\tstarted" in log or "base_remove\tended at once (code 0)" in log


def test_values_are_never_taken_for_options(ws, monkeypatch, capsys):
    """A path or an id that starts with "-" ("--rollback", "--help") reaches the command as a value: after "--", or
    glued to its option; the command then refuses it as a package or an id."""
    from assistant_x.base import cli

    started = []
    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: started.append(cmd) or (True, ""))
    base_tools.remove("--rollback")
    base_tools.update("--help")
    base_tools.export("--x.axbase", "--id", "--1", codes="default", name_en="--name")
    for cmd in started:
        i = cmd.index("--")
        assert all(
            not a.startswith("-") or "=" in a or a in ("--confirm", "--resume", "--rollback", "--include-personal")
            for a in cmd[3:i]
        ), cmd
        assert len(cmd) == i + 2 and cmd[i + 1].startswith("--")
    assert "--id=--id" in started[-1] and "--name-en=--name" in started[-1]
    assert cli.main(["remove", "--", "--rollback"]) == 1  # an id, refused as one: nothing undone
    assert "is not the id of a package" in capsys.readouterr().out


def test_an_interrupted_change_is_reported(ws, monkeypatch):
    """A base transaction whose journal stayed open (the server and its job were closed mid-way) shows in base_status,
    in intake_status and once in the first answer of the server, with the calls that go on or undo it."""
    from assistant_x.base import install as B
    from assistant_x.core import workspace
    from assistant_x.server import mcp_server

    stage = workspace.current().data / "w" / "0123abcd"
    stage.mkdir(parents=True)
    journal = {"kind": "update", "id": "test-a", "package": "C:/p/a.axbase", "started": "2026-10-26T01:02:03"}
    (stage / B.JOURNAL).write_text(json.dumps({**journal, "steps": ["marker", "backup"]}), encoding="utf-8")
    lines = base_tools.open_journals()
    assert len(lines) == 1 and "base update of test-a was interrupted" in lines[0] and "marker, backup" in lines[0]
    assert 'base_update("C:/p/a.axbase", resume=True)' in lines[0] and "rollback=True" in lines[0]
    assert "## Interrupted" in base_tools.status()
    monkeypatch.setattr(intake_tools, "_intake", lambda *a, **k: (1, ""))
    assert "## Interrupted base change" in intake_tools.status()
    monkeypatch.setattr(mcp_server, "_noticed", False)
    assert "tell the user" in mcp_server.start_notice() and mcp_server.start_notice() == ""  # once


def test_a_token_is_bound_to_the_workspace_and_the_package(ws, package_a, tmp_path, monkeypatch):
    """A token confirms only in the workspace of its plan and only the package file of its plan: one made in another
    workspace, or for a file replaced at the same path since, is refused."""
    import shutil

    from assistant_x.base import registry
    from assistant_x.core import workspace
    from assistant_x.server import confirm as K

    pkg = tmp_path / "p.axbase"
    shutil.copyfile(package_a, pkg)
    token = K.issue("base_install", str(pkg))
    other = tmp_path / "other"
    libraries.make_b(str(other))
    monkeypatch.setenv("AX_WORKSPACE", str(other))
    workspace.reset()
    assert "another workspace" in K.check("base_install", str(pkg), token)
    monkeypatch.setenv("AX_WORKSPACE", str(ws))
    workspace.reset()
    token = K.issue("base_install", str(pkg))
    pkg.unlink()
    X.export(
        load_config(make_library(str(tmp_path / "C"))),
        settings.load(str(tmp_path / "C"))[1],
        str(pkg),
        "test-a",
        "1.0",
        say=lambda s: None,
    )
    assert "package file changed" in K.check("base_install", str(pkg), token)  # the same path, another file
    token = K.issue("base_install", str(pkg))
    assert K.check("base_install", str(pkg), token) == ""
    registry.put(ws / "index", {"id": "test-a", "version": "1.0", "installed": "2026-10-26"})
    token = K.issue("base_remove", "test-a")
    registry.put(ws / "index", {"id": "test-a", "version": "1.1", "installed": "2026-10-27"})
    assert "installed package changed" in K.check("base_remove", "test-a", token)


def test_the_client_asks_the_user_where_it_can(ws, monkeypatch):
    """Through a real MCP client that takes elicitation, a confirmed change with a valid token is put to the user by
    the client itself: a "no" changes nothing, a "yes" goes on. A client without elicitation keeps the token flow."""
    import anyio
    from mcp import types
    from mcp.client.client import Client

    from assistant_x.base import registry
    from assistant_x.server import mcp_server

    registry.put(ws / "index", {"id": "test-a", "version": "1.0", "installed": "2026-10-26"})
    started, asked = [], []

    async def answer(context, params, yes):
        asked.append(params.message)
        return (
            types.ElicitResult(action="accept", content={"confirm": True}) if yes else types.ElicitResult(action="decline")
        )

    async def call(cb):
        token = re.search(r'token="(\w+)"', base_tools.remove("test-a"))[1]
        async with Client(mcp_server.mcp, mode="legacy", **({"elicitation_callback": cb} if cb else {})) as c:
            r = await c.call_tool("base_remove", {"id": "test-a", "confirm": True, "token": token})
        return r.content[0].text

    monkeypatch.setattr(intake_tools, "_start", lambda kind, cmd, **env: started.append(cmd) or (True, ""))
    no = anyio.run(call, lambda c, p: answer(c, p, False))
    changes = lambda: [c for c in started if "--confirm" in c]  # noqa: E731 — the plans start too
    assert no.startswith("The user said no") and not changes() and "remove the base package test-a" in asked[0]
    yes = anyio.run(call, lambda c, p: answer(c, p, True))
    assert "started in the background" in yes and len(changes()) == 1 and len(asked) == 2
    assert "started in the background" in anyio.run(call, None) and len(asked) == 2  # no elicitation: the token


def test_no_install_token_for_an_installed_package(ws, monkeypatch):
    """base_status shows the questions of a finished inspect, but mints no install token when that version of the
    package is installed already."""
    from assistant_x.base import registry

    report = {"ok": True, "path": str(ws / "a.axbase"), "package": {"id": "test-a", "version": "1.0"}, "questions": []}
    os.makedirs(intake_tools.jobs_dir(), exist_ok=True)
    with open(base_tools._report_path(), "w", encoding="utf-8") as f:
        json.dump(report, f)
    job = {"id": "x", "pid": 2**30, "created": 0, "cmd": [], "started": time.time()}  # no such process: ended
    monkeypatch.setattr(intake_tools, "_job", lambda kind: job if kind == "base_inspect" else None)
    assert 'base_install("' in base_tools.status()
    registry.put(ws / "index", {"id": "test-a", "version": "1.0", "installed": "2026-10-26"})
    assert 'base_install("' not in base_tools.status()
