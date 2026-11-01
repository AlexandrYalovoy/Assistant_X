# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The repository names no company (the author's rule): no word of a tracked text file is one of the names below. The
names are kept as the first 16 hex digits of the sha256 of the word in lower case, so this test names none itself
(audit 9 I-02: the abbreviation of a company in the design codes of two fixtures)."""

import hashlib, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = {  # sha256(word.lower())[:16] of the names of oil and gas companies, in Russian and in Latin letters
    "ed224a8d63624b14",
    "be77035d0a609bbe",
    "1b8767864eef50ff",
    "06d1c1027872ab91",
    "c6147f09659bb21e",
    "333c33cfc4bd188c",
    "e22182057439268e",
    "d9bdd8642c2626ae",
    "57cb69544a1d6d69",
    "fa01d511f9a8e913",
    "60dfd768e73038e3",
    "25ceb941ff14362c",
    "4c84de86c8adb0ed",
    "c82e6ca375344794",
    "95b898ba4c9092ff",
}
TEXT = (".py", ".md", ".json", ".toml", ".txt", ".bat", ".ps1", ".yml", ".yaml", ".cfg", ".csv")


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")  # noqa: S603
    return [ROOT / p for p in out.stdout.splitlines() if p.lower().endswith(TEXT)]


def test_no_company_is_named():
    hits = []
    for p in tracked():
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for w in re.findall(r"[^\W\d_]+", line):
                if hashlib.sha256(w.lower().encode("utf-8")).hexdigest()[:16] in NAMES:
                    hits.append(f"{p.relative_to(ROOT)}:{n}")
    assert not hits, hits
