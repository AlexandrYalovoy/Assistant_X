# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/check.py runs the checks of check.ps1 where PowerShell scripts may not run (an agent's shell, Linux): the
same pytest options, --fast, --log FOLDER and the arguments it does not know passed on."""

import importlib.util, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load():
    spec = importlib.util.spec_from_file_location("check_script", os.path.join(ROOT, "scripts", "check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_pytest_options(tmp_path):
    check = load()
    plain = check.pytest_args()
    assert plain[:3] == [sys.executable, "-m", "pytest"] and plain[-1] == os.path.join(check.ROOT, "tests")
    fast = check.pytest_args(fast=True, log=str(tmp_path), extra=["-k", "bridge"])
    assert ["-m", "not slow"] == fast[fast.index("-m", 3) : fast.index("-m", 3) + 2]
    assert "--durations=30" in fast and f"--junitxml={tmp_path / 'junit.xml'}" in fast and fast[-2:] == ["-k", "bridge"]


def test_the_powershell_and_the_python_check_agree():
    """The two scripts name the same pytest options: a change to one must reach the other."""
    ps1 = open(os.path.join(ROOT, "scripts", "check.ps1"), encoding="utf-8").read()
    for option in ("-rA", "--durations=30", "no:cacheprovider", "not slow", "junit"):
        assert option in ps1
