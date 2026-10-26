# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An English library under each profile (the default "general" and "oil-gas-ru"): the workspace of most tests reads
Russian documents with the oil and gas profile, so the default configuration of a user with English documents is
checked here end to end — build, check, the search by words, the book map with the references of the English pack,
the card of a document. Each profile runs in its own process (the language packs are read once per process)."""

import json, os, subprocess, sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

DOCS = [  # code, shelf folder, title, doc_type, pages
    (
        "N-00001",
        "01_Standards",
        "Separator design practice",
        "standard",
        [
            "# 1. Scope\n\nThis practice covers gas-liquid separators. See Table 2 for the design velocities.",
            "Table 2 Design velocities\n\n| Service | Velocity |\n|---|---|\n| Gas | 3 m/s |\n\n# 2. Sizing\n\n"
            "The vessel diameter follows equation (4) and Figure 1.",
        ],
    ),
    (
        "L-00001",
        "02_Literature",
        "Handbook of centrifugal pumps",
        "handbook",
        [
            "# Chapter 1 Pumps\n\nA centrifugal pump raises the pressure of the liquid with an impeller.",
            "# Chapter 2 Seals\n\nMechanical seals keep the liquid in the casing; see Section 1.2 for the flush plans.",
        ],
    ),
]

PROBE = r"""
import json, sys
from assistant_x.core.common import load_config
from assistant_x.search import check_index
from assistant_x.search.retrieval import Library
cfg = load_config(sys.argv[1])
lib = Library(cfg)
hits = lib.search("separator design velocities", dense=False, k=3)
print(json.dumps({"errors": check_index.run(cfg, quiet=True),
                  "top": [h["code"] for h in hits][:1],
                  "pump": [h["code"] for h in lib.search("centrifugal pump impeller", dense=False, k=3)][:1],
                  "map": lib.book_map("N-00001", 2),
                  "doc": lib.doc("L-00001")["title"]}))
"""


def make(root, profile):
    from assistant_x.core import card as C
    from tests.search.conftest import text_pdf, write

    for code, folder, title, doc_type, pages in DOCS:
        pdf = os.path.join(root, "library", folder, f"{code}_{title.replace(' ', '-')}.pdf")
        os.makedirs(os.path.dirname(pdf), exist_ok=True)
        text_pdf(pdf, [p.splitlines()[0] for p in pages])
        card = C.complete(
            {
                "schema": 1,
                "code": code,
                "section": code[0],
                "doc_type": doc_type,
                "doc": {
                    "title": {"en": title},
                    "lang": ["en"],
                    "year": 2024,
                    "topics": ["equipment"],
                    "summary": f"{title}: an English test document.",
                    "keywords": {"en": ["equipment"]},
                },
                "file": {
                    "library": os.path.relpath(pdf, root).replace(os.sep, "/"),
                    "text": f"index/texts/{code}.md",
                    "format": {"kind": "pdf_text", "pages": len(pages)},
                },
                "intake": {"date": "2026-10-26", "personal": False},
            }
        )
        C.dump(card, os.path.join(root, "index", "cards", f"{code}.json"))
        write(
            os.path.join(root, "index", "texts", f"{code}.md"),
            "".join(f"=== page {i + 1} ===\n\n{p}\n\n" for i, p in enumerate(pages)),
        )
    path = os.path.join(root, "assistant_x.toml")
    write(
        path,
        f'profile = "{profile}"\n\n[documents]\nlanguages = ["en"]\n\n[paths]\ndb = "search/db"\n'
        'models = "models"\n\n[search]\nrerank = false\n',
    )
    return path


@pytest.mark.parametrize("profile", ["general", "oil-gas-ru"])
def test_an_english_library(tmp_path, profile):
    root = str(tmp_path / "ws")
    path = make(root, profile)
    env = {**os.environ, "AX_WORKSPACE": root, "AX_CONFIG": path, "PYTHONUTF8": "1"}
    run = lambda *args: subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",  # noqa: E731
        env=env,
        timeout=600,
        cwd=str(TESTS.parent),
    )
    p = run("-m", "assistant_x.search.build_index", "--config", path)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    p = run("-c", PROBE, path)
    assert p.returncode == 0, p.stderr[-3000:]
    out = json.loads(p.stdout.splitlines()[-1])
    assert out["errors"] == 0 and out["top"] == ["N-00001"] and out["pump"] == ["L-00001"]
    assert out["doc"] == "Handbook of centrifugal pumps"
    book = out["map"]
    assert "Scope" in book and "Sizing" in book and "table 2 — 2" in book  # the caption of the English pack
