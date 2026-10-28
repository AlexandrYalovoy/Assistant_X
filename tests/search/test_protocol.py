# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The server as any app sees it, through a plain MCP client without elicitation: titles and annotations of every
tool, the reader set, library_guide, texts without an app name, argument schemas an OpenAI strict function takes,
the compact mode."""

import copy

import anyio
import pytest
from mcp.client.client import Client

from assistant_x.server import mcp_server, texts, toolsets


@pytest.fixture
def server(lib, monkeypatch):
    monkeypatch.setattr(mcp_server, "_lib", lib)
    monkeypatch.setattr(mcp_server, "_owner", object())
    return mcp_server


def listed(mode="legacy"):
    async def go():
        async with Client(mcp_server.mcp, mode=mode) as c:
            return (await c.list_tools()).tools, c.instructions

    return anyio.run(go)


def called(name, args):
    async def go():
        async with Client(mcp_server.mcp, mode="legacy") as c:
            return await c.call_tool(name, args)

    return anyio.run(go)


def test_every_tool_has_a_title_and_annotations():
    tools, _ = listed()
    assert len(tools) >= 23
    for t in tools:
        a = t.annotations
        assert t.title and a is not None, t.name
        assert a.read_only_hint is not None and a.destructive_hint is not None and a.open_world_hint is False, t.name
        assert not (a.read_only_hint and a.destructive_hint), t.name
    by = {t.name: t.annotations for t in tools}
    for name in toolsets.READER:
        assert by[name].read_only_hint, name
    for name in ("intake_apply", "library_remove", "base_install", "base_update", "base_remove"):
        assert by[name].destructive_hint and not by[name].read_only_hint, name


def test_no_app_name_in_what_the_model_reads(server):
    """The instructions, the titles, the descriptions and the guide speak to any app: no "Claude" in them."""
    tools, instructions = listed()
    assert instructions == texts.INSTRUCTIONS and "library_guide" in instructions
    for t in tools:
        assert "Claude" not in f"{t.title} {t.description}", t.name
    assert "Claude" not in texts.INSTRUCTIONS and "Claude" not in server.library_guide()


def test_the_guide_through_the_client(server):
    r = called("library_guide", {})
    text = r.content[0].text
    assert "[code, p. printed, PDF N]" in text and "verify_quote" in text and "`N`" in text  # rules and the shelves
    assert "data, not commands" in text and len(text) < 8000


def test_search_through_a_plain_client(server):
    """A client that cannot ask the user (no elicitation, as LM Studio) reads the library as any other."""
    r = called("search_library", {"query": "обводнённости"})
    assert not r.is_error and "[N-00001, PDF" in r.content[0].text


def test_page_image_has_a_text_beside_the_picture(server):
    r = called("page_image", {"code": "N-00001", "page": 1})
    kinds = [c.type for c in r.content]
    assert kinds == ["text", "image"] and "If you cannot see images" in r.content[0].text


def strict(schema):
    """The schema as an OpenAI strict function takes it: every property required (an optional one nullable), no
    other properties, no default; AssertionError when it cannot be (an object of free keys)."""
    s = {k: v for k, v in schema.items() if k not in ("default", "title")}
    if "anyOf" in s:
        s["anyOf"] = [strict(x) for x in s["anyOf"]]
    if s.get("type") == "array":
        assert "items" in s and isinstance(s["items"], dict), schema
        s["items"] = strict(s["items"])
    if s.get("type") == "object":
        props = s.get("properties")
        assert isinstance(props, dict), f"an object of free keys: {schema}"
        assert s.get("additionalProperties") in (None, False), schema
        required = set(s.get("required") or [])
        s["properties"] = {}
        for k, v in props.items():
            v = strict(v)
            if k not in required and not any(x.get("type") == "null" for x in v.get("anyOf", [])):
                v = {"anyOf": [v, {"type": "null"}]}
            s["properties"][k] = v
        s["required"] = list(props)
        s["additionalProperties"] = False
    allowed = {"type", "properties", "required", "additionalProperties", "items", "anyOf", "enum", "description"}
    assert set(s) <= allowed, f"keywords strict mode refuses: {set(s) - allowed} in {schema}"
    return s


def test_reader_arguments_fit_openai_strict_functions():
    """Codex and the ChatGPT app may send the tools as strict functions: the reading tools convert without loss."""
    tools, _ = listed()
    for t in tools:
        if t.name in toolsets.READER:
            strict(t.input_schema)


def test_the_reader_set_and_the_compact_mode(server, monkeypatch):
    """serve --tools reader --compact: the 8 reading tools, one-sentence descriptions, answers within the limit."""
    manager = server.mcp._tool_manager
    monkeypatch.setattr(manager, "_tools", {k: copy.copy(v) for k, v in manager._tools.items()})
    monkeypatch.setattr(server, "COMPACT", False)
    monkeypatch.setattr(toolsets, "COMPACT_CHARS", 300)
    server.limit_tools(*server.options(["--tools", "reader", "--compact"]))
    tools, _ = listed()
    assert sorted(t.name for t in tools) == sorted(toolsets.READER)
    assert all(t.description.count(". ") == 0 for t in tools)
    text = called("search_library", {"query": "обводнённости", "k": 20}).content[0].text
    assert len(text) <= 300 + len(toolsets.CUT_NOTE) + 10 and "compact mode" in text
    with pytest.raises(SystemExit, match="--tools takes"):
        server.options(["--tools", "some"])


def test_fit_and_first_sentence():
    assert toolsets.first_sentence("Find fragments. Returns the code.\n  More.") == "Find fragments."
    assert toolsets.fit("short") == "short"
    long = "line\n" * 3000
    out = toolsets.fit(long, 100)
    assert out.startswith("line\n") and "Cut at 100 characters" in out and len(out) < 100 + len(toolsets.CUT_NOTE) + 5
    assert toolsets.compact_arguments("search_library", {"query": "q", "k": 20})["k"] == toolsets.COMPACT_K
    assert toolsets.allowed("intake_run", "all") and not toolsets.allowed("intake_run", "reader")
