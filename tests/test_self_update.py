# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x update --from URL (setup/self_update.py) without the network: the address of a project, the latest
release with a tag and its wheel, the sum of SHA256SUMS that must match, nothing done for the same version, and the
apps connected back to the old python when a step of the new version fails."""

import hashlib, json, os

import pytest

from assistant_x.setup import self_update as U

WHEEL = "assistant_x-9.9.9-py3-none-any.whl"


def test_the_address_of_a_project():
    assert U.source("https://github.com/owner/assistant-x") == ("github", "owner", "assistant-x")
    assert U.source("https://github.com/owner/assistant-x.git/") == ("github", "owner", "assistant-x")
    assert U.source("https://gitflic.ru/project/owner/assistant-x") == ("gitflic", "owner", "assistant-x")
    with pytest.raises(SystemExit):
        U.source("https://example.org/owner/assistant-x")


def release(monkeypatch, version="9.9.9", sums=True, draft=False):
    assets = [{"name": f"assistant_x-{version}-py3-none-any.whl", "browser_download_url": "https://x/wheel"}]
    if sums:
        assets.append({"name": "SHA256SUMS", "browser_download_url": "https://x/sums"})
    monkeypatch.setattr(
        U, "get_json", lambda url: {"tag_name": f"v{version}", "draft": draft, "prerelease": False, "assets": assets}
    )


def test_the_latest_release_with_a_tag(monkeypatch):
    release(monkeypatch)
    rel = U.latest("github", "o", "r")
    assert rel["version"] == "9.9.9" and rel["wheel"] == WHEEL and rel["tag"] == "v9.9.9"
    release(monkeypatch, draft=True)
    with pytest.raises(SystemExit):
        U.latest("github", "o", "r")


def test_the_same_version_does_nothing(monkeypatch, capsys):
    from assistant_x import __version__

    release(monkeypatch, version=__version__)
    monkeypatch.setattr(U, "download", lambda *a, **k: pytest.fail("nothing is downloaded"))
    assert U.update("https://github.com/o/r") == 0
    assert "Nothing to do" in capsys.readouterr().out


def test_a_wheel_without_its_sum_is_refused(monkeypatch, tmp_path):
    from assistant_x.setup import downloads

    release(monkeypatch, sums=False)
    with pytest.raises(SystemExit, match="no SHA256SUMS"):
        U.download(U.latest("github", "o", "r"), str(tmp_path))
    release(monkeypatch)
    data = b"the wheel"

    def fetch(url, sha, path, say=print):
        body = b"0" * 64 + b"  other.whl\n" if url.endswith("sums") else data
        if sha and hashlib.sha256(body).hexdigest() != sha:
            raise SystemExit("sha256 mismatch")
        open(path, "wb").write(body)
        return path

    monkeypatch.setattr(downloads, "fetch", fetch)
    with pytest.raises(SystemExit, match="names no sum"):
        U.download(U.latest("github", "o", "r"), str(tmp_path))


def test_a_failed_doctor_connects_the_apps_back(monkeypatch, tmp_path, capsys):
    release(monkeypatch)
    wheel = tmp_path / WHEEL
    wheel.write_bytes(b"w")
    monkeypatch.setattr(U, "download", lambda rel, folder: str(wheel))
    calls = []
    monkeypatch.setattr(U, "install", lambda old, w, d, dry: (os.makedirs(d, exist_ok=True), "NEW-PY")[1])
    monkeypatch.setattr(U, "reconnect", lambda py, dry: calls.append(py) or 0)
    monkeypatch.setattr(U, "doctor", lambda py, dry: False)
    assert U.update("https://github.com/o/r", old_py="OLD-PY") == 1
    assert calls == ["NEW-PY", "OLD-PY"]  # the new python first, back to the old one after the failure
    assert not (tmp_path / "machine").exists() or not any("venv-9.9.9" in p for p in os.listdir(tmp_path))
    assert "connected back to OLD-PY" in capsys.readouterr().out


def test_a_good_update_keeps_the_old_environment(monkeypatch, tmp_path):
    from assistant_x.core import workspace

    release(monkeypatch)
    monkeypatch.setattr(U, "download", lambda rel, folder: "w.whl")
    monkeypatch.setattr(U, "install", lambda old, w, d, dry: (os.makedirs(d, exist_ok=True), "NEW-PY")[1])
    monkeypatch.setattr(U, "reconnect", lambda py, dry: 0)
    monkeypatch.setattr(U, "doctor", lambda py, dry: True)
    assert U.update("https://github.com/o/r", old_py=str(tmp_path / "venv" / "Scripts" / "python.exe")) == 0
    assert (workspace.machine_dir() / "venv-9.9.9").is_dir()
    # the python in use for Install-Base.bat and Update.bat: the new environment
    assert (workspace.machine_dir() / "python.txt").read_text(encoding="utf-8").strip() == "NEW-PY"


def test_update_from_goes_to_the_update_of_the_program(monkeypatch):
    from assistant_x.clients import connect

    seen = []
    monkeypatch.setattr(U, "main", lambda argv: seen.append(argv) or 0)
    assert connect.update_main(["--from", "https://github.com/o/r", "--dry-run"]) == 0
    assert seen == [["--from", "https://github.com/o/r", "--dry-run"]]
    assert json.dumps(seen)
