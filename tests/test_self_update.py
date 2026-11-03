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


# ---------- the chain of environments, the constraints, the environment in use (audit of 2026-11-03) ----------


def test_a_third_environment_still_sees_the_packages_of_the_first(tmp_path):
    """I-02: a folder named by a .pth line never has its own .pth files read, so each update names the whole chain:
    the packages of the first environment (and those its own .pth files add, pywin32's) are seen from the third."""
    import subprocess, sys

    orig, a, b, c = (tmp_path / n for n in ("orig", "a", "b", "c"))
    for d in (orig, a, b, c):
        d.mkdir()
    (orig / "first_env_module.py").write_text("X = 1\n", encoding="utf-8")
    (orig / "extra").mkdir()
    (orig / "extra" / "pth_added_module.py").write_text("Y = 2\n", encoding="utf-8")
    (orig / "extra.pth").write_text(str(orig / "extra") + "\n", encoding="utf-8")
    (a / U.PREVIOUS).write_text(str(orig) + "\n", encoding="utf-8")  # an update before the fix: one plain line
    (b / U.PREVIOUS).write_text(U.previous_pth(U.chain(str(a))), encoding="utf-8")
    (c / U.PREVIOUS).write_text(U.previous_pth(U.chain(str(b))), encoding="utf-8")
    assert U.chain(str(b)) == [str(b), str(a), str(orig)]
    code = f"import site; site.addsitedir({str(c)!r}); import first_env_module, pth_added_module"
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_the_new_environment_takes_the_constraints_of_the_release(monkeypatch, tmp_path):
    """I-03: the wheel is installed with -c constraints.txt of the release (from the wheel), as setup/install.py does;
    I-02: the .pth of the new environment names the chain of the old one."""
    import zipfile

    from assistant_x.setup import constraints

    old_site, new_site = tmp_path / "old_site", tmp_path / "new_site"
    old_site.mkdir()
    new_site.mkdir()
    (old_site / U.PREVIOUS).write_text(str(tmp_path / "first_site") + "\n", encoding="utf-8")
    wheel = tmp_path / "dl" / WHEEL
    wheel.parent.mkdir()
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr(U.CONSTRAINTS, "numpy==1.0\n")
    cmds = []
    monkeypatch.setattr(U, "run", lambda cmd, dry: cmds.append(cmd) or 0)
    monkeypatch.setattr(U, "site_packages", lambda py: str(old_site if py == "OLD-PY" else new_site))
    U.install("OLD-PY", str(wheel), str(tmp_path / "venv-9.9.9"), False)
    pip = cmds[-1]
    assert pip[-1] == str(wheel) and "-c" in pip
    assert open(pip[pip.index("-c") + 1], encoding="utf-8").read() == "numpy==1.0\n"
    assert U.pth_dirs((new_site / U.PREVIOUS).read_text(encoding="utf-8")) == [str(old_site), str(tmp_path / "first_site")]
    wheel.write_bytes(b"not a zip")  # a wheel without the file: the constraints of this program
    U.install("OLD-PY", str(wheel), str(tmp_path / "venv-9.9.9"), False)
    assert cmds[-1][cmds[-1].index("-c") + 1] == constraints.PATH


def in_use_setup(monkeypatch, tmp_path):
    from assistant_x.clients import claude_desktop

    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.setattr(claude_desktop, "read", lambda: None)
    release(monkeypatch)
    monkeypatch.setattr(U, "download", lambda *a, **k: pytest.fail("nothing is downloaded"))
    new_dir = tmp_path / "machine" / "venv-9.9.9"
    (new_dir / "Scripts").mkdir(parents=True)
    (new_dir / "keep.txt").write_text("in use", encoding="utf-8")
    return new_dir


def test_the_environment_in_use_is_never_removed(monkeypatch, tmp_path, capsys):
    """I-04: --force on the version in use, or a rerun when the apps already start venv-<version>: refused, the folder
    stays."""
    from assistant_x import clients as K

    new_dir = in_use_setup(monkeypatch, tmp_path)
    py = str(new_dir / "Scripts" / "python.exe")
    assert U.update("https://github.com/o/r", force=True, old_py=py) == 1
    assert (new_dir / "keep.txt").exists() and "the environment in use" in capsys.readouterr().out
    K.remember("codex", {"python": py})  # an app starts it, the update runs from an older environment
    assert U.update("https://github.com/o/r", old_py=str(tmp_path / "venv" / "Scripts" / "python.exe")) == 1
    assert (new_dir / "keep.txt").exists()


def test_ctrl_c_midway_connects_the_apps_back(monkeypatch, tmp_path):
    """I-04: any stop of the install (Ctrl+C too) connects the apps back to the old python and removes the half-made
    environment; the interruption goes on."""
    in_use_setup(monkeypatch, tmp_path)
    (tmp_path / "machine" / "venv-9.9.9" / "keep.txt").unlink()
    monkeypatch.setattr(U, "download", lambda rel, folder: "w.whl")
    calls = []
    monkeypatch.setattr(U, "reconnect", lambda py, dry: calls.append(py) or 0)

    def stop(*a):
        raise KeyboardInterrupt

    monkeypatch.setattr(U, "install", stop)
    with pytest.raises(KeyboardInterrupt):
        U.update("https://github.com/o/r", old_py=str(tmp_path / "venv" / "Scripts" / "python.exe"))
    assert calls == [str(tmp_path / "venv" / "Scripts" / "python.exe")]
    assert not (tmp_path / "machine" / "venv-9.9.9").exists()
