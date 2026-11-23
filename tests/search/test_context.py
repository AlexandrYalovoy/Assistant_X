# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bounded one-command context: full best pages without duplicating their text in the search matches."""

import json

from assistant_x.search import context
from assistant_x.server import mcp_server


def test_balanced_context_is_bounded_and_has_full_pages(lib, monkeypatch, capsys):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    monkeypatch.setattr(mcp_server, "_owner", object())
    out = context.build("обводнённости", k=4, pages=2, max_chars=4000)
    assert out["status"] == "ok" and 1 <= len(out["pages"]) <= 2
    assert len(out["matches"]) <= 4
    assert all("=== page " in p["text"] and p["citation"] for p in out["pages"])
    chosen = {(p["code"], p["pdf_page"]) for p in out["pages"]}
    for hit in out["matches"]:
        if (hit["code"], hit["pdf_page"]) in chosen:
            assert hit["text"] == ""
        else:
            assert len(hit["text"]) <= 700
    encoded = json.dumps(out, ensure_ascii=False)
    assert len(encoded) < 12000
    context.main(["обводнённости", "--k", "2", "--pages", "1", "--max-chars", "3000"])
    cli = json.loads(capsys.readouterr().out)
    assert len(cli["pages"]) == 1 and cli["limits"]["k"] == 2


def test_cost_modes_have_deliberate_limits():
    assert context.MODES["fast"] == (3, 1, 12000)
    assert context.MODES["balanced"] == (4, 2, 24000)
    assert context.MODES["deep"] == (8, 5, 40000)
    assert context.MODES["fast"][2] < context.MODES["balanced"][2] < context.MODES["deep"][2]


def test_deep_reads_pages_beside_the_best_fragments(lib, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    monkeypatch.setattr(mcp_server, "_owner", object())
    out = context.build("обводнённости", k=4, pages=3, max_chars=6000)
    assert len(out["pages"]) == 3 and any(p["expanded"] for p in out["pages"])
    assert any(not p["expanded"] for p in out["pages"])
    assert all("=== page " in p["text"] for p in out["pages"])


def test_internal_key_norms_cannot_exceed_the_public_match_budget(lib, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    monkeypatch.setattr(mcp_server, "_owner", object())
    extra = lib.search("обводнённости", k=4)
    monkeypatch.setattr(mcp_server, "find_fragments", lambda *a, **kw: extra)
    out = context.build("обводнённости", k=2, pages=1, max_chars=3000)
    assert len(out["matches"]) == 2 and len(out["pages"]) == 1
