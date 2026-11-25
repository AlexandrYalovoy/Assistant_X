# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One release preflight: versioned documents, generated files, dependency pins, lint and tests.

    python scripts/release_check.py [--fast] [--allow-dirty] [--skip-tests]

A release commit must use a clean Git worktree. During development --allow-dirty permits edits; it does not skip any
content check. --fast excludes the slow tests. The GitHub tag is still pushed by the maintainer after green CI.
"""

import argparse, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def problems(version, changelogs, security):
    """Version consistency problems in the release documents."""
    out = []
    rx = re.compile(rf"^## {re.escape(version)}(?:\s+—\s+|\s+)(unreleased|\d{{4}}-\d{{2}}-\d{{2}})\s*$", re.M)
    for name, text in changelogs.items():
        if not rx.search(text):
            out.append(f"{name}: no section ## {version} — unreleased or ## {version} — YYYY-MM-DD")
    if version not in security:
        out.append(f"SECURITY.md: does not name the current version {version}")
    return out


def run(cmd, env):
    print("+ " + " ".join(str(x) for x in cmd), flush=True)
    return subprocess.run([str(x) for x in cmd], cwd=ROOT, env=env).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fast", action="store_true", help="exclude tests marked slow")
    ap.add_argument("--allow-dirty", action="store_true", help="allow a development worktree with edits")
    ap.add_argument("--skip-tests", action="store_true", help="documents and lint only")
    a = ap.parse_args(argv)
    from assistant_x import __version__
    from assistant_x.setup import constraints, gen_docs

    bad = problems(
        __version__,
        {name: (ROOT / name).read_text(encoding="utf-8") for name in ("CHANGELOG.md", "CHANGELOG.ru.md")},
        (ROOT / "SECURITY.md").read_text(encoding="utf-8"),
    )
    stale = [
        str(p.relative_to(ROOT))
        for p, text in gen_docs.targets().items()
        if not p.exists() or p.read_text(encoding="utf-8") != text
    ]
    bad += [f"{p}: out of date; run assistant-x gen-docs" for p in stale]
    have, want = constraints.current(), constraints.read()
    diff = sorted(k for k in set(have) | set(want) if have.get(k, (0, None))[1] != want.get(k, (0, None))[1])
    bad += [f"constraints.txt: {k}: installed {have.get(k, (0, '-'))[1]}, pinned {want.get(k, (0, '-'))[1]}" for k in diff]
    if not a.allow_dirty:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if dirty:
            bad.append("Git worktree is not clean (during development use --allow-dirty)")
    env = dict(os.environ, PYTHONUTF8="1", AX_NO_OPEN="1", PYTHONDONTWRITEBYTECODE="1")
    for p in bad:
        print("ERROR:", p)
    if bad:
        return 1
    py = sys.executable
    for cmd in ([py, "-m", "ruff", "check", ROOT], [py, "-m", "ruff", "format", "--check", ROOT]):
        if run(cmd, env):
            return 1
    if not a.skip_tests:
        cmd = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", ROOT / "tests"]
        if a.fast:
            cmd += ["-m", "not slow"]
        if run(cmd, env):
            return 1
    print(f"release preflight passed for {__version__}" + (" (development worktree)" if a.allow_dirty else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
