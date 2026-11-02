# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The installation on a new PC from a git checkout (no medium, no packages folder): the steps before the packages
run under a bare Python (no numpy, no other package) and with no machine folder yet; Setup.bat downloads Python from
python.org only signed by the Python Software Foundation, takes an installer only when the file is there, and every
double-click file passes the exit code of its command on."""

import os, subprocess, sys

import pytest

from assistant_x.setup import prepare_media

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAVY = ("numpy", "torch", "onnxruntime", "sentence_transformers", "transformers", "fitz", "pymupdf", "mcp", "scipy")
BLOCK = f"""
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {HEAVY!r}:
            raise ModuleNotFoundError("No module named " + repr(name) + " (a new PC: not installed yet)")
sys.meta_path.insert(0, Block())
"""


def bare(code, tmp_path, *args):
    """Run code under a Python that cannot import any package, with a machine folder and a workspace not made yet."""
    env = dict(
        os.environ,
        AX_MACHINE_DIR=str(tmp_path / "machine"),
        AX_WORKSPACE=str(tmp_path / "ws"),
        AX_MCP_LOCK_FILE="",
        AX_HEAVY_LOCK_FILE="",
        PYTHONUTF8="1",
    )
    return subprocess.run(
        [sys.executable, "-c", BLOCK + code, *args], cwd=CODE, env=env, capture_output=True, text=True, timeout=600
    )


def test_the_steps_before_the_packages_need_no_package_and_no_machine_folder(tmp_path):
    """A colleague's first installation: the check of a running server imported numpy (ModuleNotFoundError), and
    python.txt was written into a machine folder nobody had made yet."""
    r = bare(
        "from assistant_x.setup import install\n"
        "assert install.server_running() is False\n"
        "install.remember_python(sys.executable)\n"
        "print(open(install.os.path.join(install.LOCAL, install.CURRENT_PYTHON), encoding='utf-8').read().strip())\n",
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == sys.executable


def test_a_trial_installation_on_a_new_pc(tmp_path):
    """install --dry-run on a bare Python and a new PC goes through to its end: no step before the packages imports
    a package (install_packages and the later steps run in the new environment)."""
    r = bare(
        "import runpy\nsys.argv = ['install', '--dry-run', '--yes', '--no-register']\n"
        "runpy.run_module('assistant_x.setup.install', run_name='__main__')\n",
        tmp_path,
    )
    assert "ModuleNotFoundError" not in r.stderr + r.stdout, r.stderr[-3000:]
    assert r.returncode == 0, (r.stdout[-2000:], r.stderr[-2000:])
    assert "trial run" in r.stdout


def test_setup_bat_downloads_python_only_signed_and_takes_only_a_file_that_is_there():
    bat = open(os.path.join(CODE, "Setup.bat"), encoding="utf-8").read()
    assert f'set "PYFULL={prepare_media.LAST_INSTALLER["3.11"]}"' in bat  # one version with prepare-media
    assert "https://www.python.org/ftp/python/%PYFULL%/python-%PYFULL%-amd64.exe" in bat
    assert "Get-AuthenticodeSignature" in bat and "Python Software Foundation" in bat and "Status -ne 'Valid'" in bat
    # the signature is checked on the .part before it takes the name of the installer, and only then it runs
    dl = bat.split("\n:download_python", 1)[1]
    assert (
        dl.index("Get-AuthenticodeSignature") < dl.index('move /y "%PYEXE%.part" "%PYEXE%"') < dl.index('"%PYEXE%" /quiet')
    )
    assert dl.index("if defined DRY (") < dl.index("Invoke-WebRequest")  # a trial run downloads nothing
    assert 'do if exist "%%~f" set "PYEXE=%%~f"' in bat and 'if defined PYEXE if not exist "%PYEXE%" set "PYEXE="' in bat
    assert 'if not defined PY if not exist "%PACKS%\\python-*.exe" call :download_python' in bat


@pytest.mark.parametrize("name", ["Setup.bat", "Update.bat", "Install-Base.bat"])
def test_the_double_click_files_pass_the_exit_code_on(name):
    bat = open(os.path.join(CODE, name), encoding="utf-8").read()
    assert 'set "RC=%errorlevel%"' in bat and bat.rstrip().count("exit /b %RC%") >= 1
    assert 'set "RC=1"' in bat  # nothing to run: a failure too


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_setup_bat_fails_when_the_installer_fails(tmp_path):
    """The installer stops (here: a wrong argument): Setup.bat says so and ends with its code, not 0."""
    env = dict(os.environ, AX_NOPAUSE="1", AX_MACHINE_DIR=str(tmp_path / "m"), AX_WORKSPACE=str(tmp_path / "ws"))
    r = subprocess.run(
        ["cmd", "/c", os.path.join(CODE, "Setup.bat"), "--dry-run", "--keep", "nobody"],
        env=env,
        capture_output=True,
        timeout=600,
    )
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 2, out[-2000:]
    assert "did not finish (code 2)" in out


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
@pytest.mark.parametrize("name", ["Update.bat", "Install-Base.bat"])
def test_update_and_install_base_fail_when_their_command_fails(tmp_path, name):
    machine = tmp_path / "m"
    machine.mkdir()
    fake = tmp_path / "python.cmd"
    fake.write_text("@exit /b 3\r\n", encoding="utf-8")
    (machine / "python.txt").write_text(str(fake) + "\n", encoding="utf-8")
    env = dict(os.environ, AX_NOPAUSE="1", AX_MACHINE_DIR=str(machine))
    r = subprocess.run(["cmd", "/c", os.path.join(CODE, name)], env=env, capture_output=True, timeout=120)
    assert r.returncode == 3, r.stdout.decode("utf-8", "replace")[-1500:]
    env["AX_MACHINE_DIR"] = str(tmp_path / "none")  # not installed: a failure too
    r = subprocess.run(["cmd", "/c", os.path.join(CODE, name)], env=env, capture_output=True, timeout=120)
    assert r.returncode == 1
