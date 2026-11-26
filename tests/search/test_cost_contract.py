# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guards for the fixed context cost of a reader, before any document text is returned."""

import json

import anyio

from assistant_x.server import mcp_server, toolsets
from assistant_x.setup import skill


def size(toolset):
    tools = [t for t in anyio.run(mcp_server.mcp.list_tools) if toolsets.allowed(t.name, toolset)]
    return len(
        json.dumps(tools, ensure_ascii=False, default=lambda x: x.model_dump() if hasattr(x, "model_dump") else str(x))
    )


def test_fixture_routes_keep_the_evidence_and_single_call_budget():
    import sys
    from assistant_x.core import proc

    run = proc.run([sys.executable, "-m", "tests.golden.fixture_routes"], capture_output=True, check=True, timeout=120)
    rows = [json.loads(line) for line in run.stdout.splitlines() if line.startswith(b'{"id"')]
    for mode, expected in (("fast", 4), ("balanced", 5), ("deep", 5)):
        single = [r for r in rows if r["mode"] == mode and r["route"] == "single"]
        steps = [r for r in rows if r["mode"] == mode and r["route"] == "steps"]
        assert len(single) == len(steps) == 5
        assert sum(r["read"] for r in single) >= expected
        assert sum(r["values"] for r in single) == 2
        assert sum(r["calls"] for r in single) < sum(r["calls"] for r in steps)
        assert sum(r["chars"] for r in single) < sum(r["chars"] for r in steps)


def test_reader_guide_is_short_and_has_no_administration():
    full, short = skill.rules(), skill.guide()
    assert len(short) < len(full) * 0.5
    assert "How to sort the user's documents" not in short
    words = " ".join(short.split())
    assert "one search" in words and "k=4" in words


def test_one_reader_schema_is_not_larger_than_one_and_much_smaller_than_reader():
    assert size("one_reader") == size("one")
    assert size("one_reader") < size("reader") * 0.2
