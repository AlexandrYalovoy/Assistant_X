# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The release preflight catches a missing changelog section and a stale current version in the guides."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release_check", ROOT / "scripts" / "release_check.py")
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


def test_release_document_versions():
    good = release_check.problems(
        "0.6.2",
        {"CHANGELOG.md": "## 0.6.2 — unreleased\n", "CHANGELOG.ru.md": "## 0.6.2 — 2026-11-22\n"},
        "0.6.2 (current)",
    )
    assert good == []
    bad = release_check.problems(
        "0.6.2",
        {"CHANGELOG.md": "## 0.6.1 — unreleased\n", "CHANGELOG.ru.md": "no version\n"},
        "0.6.1 (current)",
    )
    assert len(bad) == 3
    assert "CHANGELOG.md" in bad[0] and "SECURITY.md" in bad[-1]
