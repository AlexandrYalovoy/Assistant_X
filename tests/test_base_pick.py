# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A base package installed without a command line (setup/base_pick.py, Setup.bat, Install-Base.bat): a .axbase
beside Setup.bat is offered with its title and its count of documents, with none the dialog "Open a file" asks for
one (Cancel goes on without a base), --yes asks nothing and opens no window; Install-Base.bat shows the plan, asks
once and says how many documents went in. The messages follow the language of Windows (en, ru)."""

import json, os, types, zipfile
from pathlib import Path

import pytest

from assistant_x.setup import base_pick as B

ROOT = Path(__file__).resolve().parent.parent


def package(path, docs=7208):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "axbase.json", json.dumps({"id": "lib", "name": {"en": "Oil library", "ru": "Нефтяная"}, "documents": docs})
        )
    return path


@pytest.fixture
def lang(monkeypatch):
    monkeypatch.setattr(B, "language", lambda: "en")


def test_the_messages_of_both_languages():
    data = json.loads(B.MESSAGES.read_text(encoding="utf-8"))
    assert set(data["en"]) == set(data["ru"]) and "{documents}" in data["ru"]["done"] and "д" in data["ru"]["yes"]
    assert B.language() in ("en", "ru") and B.texts("ru")["found"].startswith("Найдена база")


def test_a_package_beside_setup_or_in_its_base_folder(tmp_path, lang):
    (tmp_path / "base").mkdir()
    one = package(tmp_path / "base" / "a.axbase")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert B.packages(tmp_path) == [one] and B.describe(one) == ("Oil library", 7208)
    assert B.describe(tmp_path / "notes.txt") == ("notes", "?")  # not a package: its name, no count


def test_a_found_package_is_offered_with_its_title_and_count(tmp_path, lang):
    p = package(tmp_path / "lib.axbase")
    asked, picked = [], []
    no_dialog = lambda *a: picked.append(a)
    assert B.choose([tmp_path], ask=lambda q: asked.append(q) or "y", pick=no_dialog) == str(p)
    assert 'A base package was found: "Oil library" (7208 documents), lib.axbase' in asked[0]
    assert B.choose([tmp_path], ask=lambda q: "n", pick=no_dialog) is None and not picked  # no: no dialog either
    assert B.choose([tmp_path], ask=lambda q: pytest.fail("asked"), pick=no_dialog, yes=True) == str(p)


def test_with_no_package_the_dialog_asks_and_cancel_goes_on(tmp_path, lang):
    said, titles = [], []
    chosen = str(package(tmp_path / "elsewhere.axbase"))
    empty = tmp_path / "medium"
    empty.mkdir()
    assert B.choose([empty], pick=lambda title, msgs: titles.append(title) or chosen, say=said.append) == chosen
    assert "Cancel: go on without a base" in titles[0]
    assert B.choose([empty], pick=lambda title, msgs: None, say=said.append) is None
    assert "Install-Base.bat" in said[-1]  # how to install it later
    assert B.choose([empty], pick=lambda *a: pytest.fail("a window with --yes"), yes=True) is None


def test_install_base_shows_the_plan_asks_once_and_counts(tmp_path, monkeypatch, lang):
    from assistant_x.core import proc

    p = package(tmp_path / "lib.axbase", docs=12)
    runs, said = [], []
    plan = "Package lib 1.0: 12 documents\nNothing changed. To install: the same command with --confirm"

    def run(cmd, **kw):
        runs.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout=plan if "--confirm" not in cmd else "Installed.", stderr="")

    monkeypatch.setattr(proc, "run", run)
    assert B.install(p, "PY", ask=lambda q: "y", say=said.append)
    assert runs[0] == ["PY", "-m", "assistant_x.base.cli", "install", str(p)] and runs[1][-1] == "--confirm"
    assert "12 documents" in said[0] and "Nothing changed" not in said[0]  # no hint of a command line
    assert said[-1].startswith("Base installed: 12 documents")
    runs.clear()
    assert not B.install(p, "PY", ask=lambda q: "n", say=said.append) and len(runs) == 1 and said[-1] == "Nothing installed."


def test_the_python_of_the_program_in_use(tmp_path, monkeypatch):
    from assistant_x.core import workspace

    monkeypatch.setattr(workspace, "machine_dir", lambda: tmp_path)
    assert B.installed_python() is None
    py = tmp_path / "venv-0.5.8" / "python.exe"
    py.parent.mkdir()
    py.write_bytes(b"")
    (tmp_path / "python.txt").write_text(f"{py}\n", encoding="utf-8")
    assert B.installed_python() == str(py)  # after an update: the new environment, not venv\


def test_the_double_clicks_of_the_medium():
    from assistant_x.setup import prepare_media

    assert prepare_media.TOP_BATS == ("Setup.bat", "Install-Base.bat", "Update.bat")
    for bat in prepare_media.TOP_BATS[1:]:
        raw = (ROOT / bat).read_bytes()
        assert raw.decode("ascii") and b"\r\n" in raw and b"python.txt" in raw and b"drag" not in raw.lower()
    assert b"assistant_x.setup.base_pick" in (ROOT / "Install-Base.bat").read_bytes()
    assert b"update --from" in (ROOT / "Update.bat").read_bytes()


def test_setup_offers_a_package_beside_it(tmp_path, monkeypatch):
    from assistant_x.setup import install

    package(tmp_path / "lib.axbase")
    monkeypatch.setattr(install.P, "MEDIUM", str(tmp_path), raising=False)
    monkeypatch.setattr(install, "YES", True)
    assert install.pick_base() == str(tmp_path / "lib.axbase")
    os.remove(tmp_path / "lib.axbase")
    assert install.pick_base() is None
