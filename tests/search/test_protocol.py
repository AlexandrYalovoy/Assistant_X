# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The server as any app sees it, through a plain MCP client without elicitation: titles and annotations of every
tool, the reader set, library_guide, texts without an app name, argument schemas an OpenAI strict function takes,
the compact mode."""

import copy, io

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
    assert (
        "[code, cl. N, table N, p. N, PDF N]" in text and "verify_quote" in text and "`N`" in text
    )  # rules and the shelves
    guide = text[text.index("# Assistant X") :]  # the notes of doctor before it depend on the PC
    assert "data, not commands" in guide and len(guide) < 8000


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
    """serve --tools reader --compact, the reference mode: its three tools, one-sentence descriptions with no hidden
    argument, the guide of the reference mode, the hits as lines ready to quote, answers within the limit."""
    manager = server.mcp._tool_manager
    monkeypatch.setattr(manager, "_tools", {k: copy.copy(v) for k, v in manager._tools.items()})
    monkeypatch.setattr(server, "COMPACT", False)
    monkeypatch.setattr(toolsets, "COMPACT_CHARS", 300)
    server.limit_tools(*server.options(["--tools", "reader", "--compact"]))
    tools, _ = listed()
    assert sorted(t.name for t in tools) == sorted(toolsets.REFERENCE)
    assert all(t.description.count(". ") == 0 for t in tools)
    text = called("search_library", {"query": "обводнённости", "k": 20}).content[0].text
    assert len(text) <= 300 + len(toolsets.CUT_NOTE) + 10 and "compact mode" in text and "reference mode" in text
    monkeypatch.setattr(toolsets, "COMPACT_CHARS", 6000)
    assert "reference mode" in called("library_guide", {}).content[0].text
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
    assert toolsets.allowed("book_map", "reader") and not toolsets.allowed("book_map", "reader", compact=True)
    assert toolsets.compact_arguments("search_library", {"query": "q"})["quotes"] is True
    assert toolsets.compact_arguments("library_guide", {}) == {"reference": True}
    listed_ = toolsets.compact_tools(
        [{"name": "search_library", "inputSchema": {"properties": {"query": {}, "quotes": {}}}}]
    )
    assert list(listed_[0]["inputSchema"]["properties"]) == ["query"]  # the bridge sets it, the model never sees it


def test_three_weak_searches_in_a_row_stop_a_small_model():
    """A small model told the library may lack the subject searched on (twelve times, no answer): the compact bridge
    counts the weak-match answers of search_library in a row, gives WEAK_STOP instead of the fragments at the third
    and starts the count again after a search that finds the subject."""
    weak = [{"type": "text", "text": "Weak match (0.82): the best fragments may be only near the question …\n\n[N-1]"}]
    good = [{"type": "text", "text": "Before citing a page, read it …\n\n[N-00390, PDF 131] …"}]
    n, out = toolsets.weak_guard(0, weak)
    assert (n, out) == (1, weak)
    n, out = toolsets.weak_guard(n, weak)
    assert (n, out) == (2, weak)
    n, out = toolsets.weak_guard(n, weak)
    assert n == 3 and out[0]["text"].startswith("STOP. The library has no document on this topic")
    n, out = toolsets.weak_guard(n, good)
    assert (n, out) == (0, good)


def test_the_bridge_stops_the_weak_searches_only_in_the_compact_mode():
    from assistant_x.server import bridge

    weak = {"content": [{"type": "text", "text": "Weak match (0.80): …"}]}
    b = bridge.Bridge(toolset="reader", compact=True, out=io.BytesIO())
    for i in range(3):
        b.calls[i] = "search_library"
        last = b.adjust({"id": i, "result": weak})
    assert last["result"]["content"][0]["text"].startswith("STOP.")
    full = bridge.Bridge(toolset="all", compact=False, out=io.BytesIO())
    for i in range(3):
        full.calls[i] = "search_library"
        last = full.adjust({"id": i, "result": weak})
    assert last["result"]["content"][0]["text"].startswith("Weak match")


def test_the_compact_bridge_puts_the_answer_form_before_every_result():
    """LM Studio without the preset gives a small model no system prompt: the compact bridge puts the form of the
    answer before every search_library and read_pages result (not before the order to stop, not in the full mode)."""
    from assistant_x.server import bridge

    page = {"content": [{"type": "text", "text": "[N-00390, PDF 131] …\nCite: [N-00390, PDF 131]"}]}
    b = bridge.Bridge(toolset="reader", compact=True, out=io.BytesIO())
    for i, name in enumerate(("search_library", "read_pages", "document_info")):
        b.calls[i] = name
        out = b.adjust({"id": i, "result": page})["result"]["content"]
        assert (out[0]["text"] == toolsets.FORM_HINT) == (name != "document_info")
    full = bridge.Bridge(toolset="all", compact=False, out=io.BytesIO())
    full.calls[9] = "search_library"
    assert full.adjust({"id": 9, "result": page})["result"]["content"] == page["content"]
    weak = {"content": [{"type": "text", "text": "Weak match (0.80): …"}]}
    for i in range(10, 13):
        b.calls[i] = "search_library"
        out = b.adjust({"id": i, "result": weak})["result"]["content"]
    assert out[0]["text"].startswith("STOP.") and len(out) == 1


def test_the_server_names_its_version_in_the_handshake():
    """Release test 0.6: a running service answered the handshake of a client with an empty version."""
    from assistant_x import __version__
    from assistant_x.server import mcp_server

    assert getattr(mcp_server.mcp, "version", __version__) == __version__


def test_the_compact_bridge_unwraps_the_one_tool():
    """The author, 2026-11-04: the one tool `library` for every app, LM Studio too. The compact bridge takes the
    command out of a call of `library` (args as a dict or as a JSON text of a small model), gives it the arguments
    of the reference mode, puts it back, answers a command outside the reference mode itself, and treats the answer
    by the command; the short description of `library` names the commands of the reference mode with their args."""
    import json

    from assistant_x.server import bridge

    sent = []
    b = bridge.Bridge(toolset="one", compact=True, out=io.BytesIO())
    b.forward = sent.append
    call = {"name": "library", "arguments": {"action": "search_library", "args": json.dumps({"query": "gas", "k": 9})}}
    b.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": call})
    args = sent[-1]["params"]["arguments"]
    assert args["action"] == "search_library" and args["args"]["k"] == toolsets.COMPACT_K and args["args"]["quotes"]
    assert b.calls[1] == "search_library"
    page = {"content": [{"type": "text", "text": "[N-00390, PDF 131] …"}]}
    assert b.adjust({"id": 1, "result": page})["result"]["content"][0]["text"] == toolsets.FORM_HINT
    b.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "library", "arguments": {"action": "intake_apply"}},
        }
    )
    assert len(sent) == 1 and b"No command 'intake_apply'" in b.out.getvalue()
    short = toolsets.compact_tools([{"name": "library", "description": "x. y.", "inputSchema": {}}])[0]["description"]
    assert short == toolsets.ONE_COMPACT and all(n in short for n in toolsets.REFERENCE)
    assert toolsets.unwrap("search_library", {"query": "q"}) == ("search_library", {"query": "q"})
    assert toolsets.unwrap("library", {"action": " read_pages ", "args": "not json"}) == ("read_pages", {})


def test_the_reference_mode_ends_every_result_with_the_order_to_quote():
    """The author, 2026-11-04: Qwen without the preset and with its thinking on wrote a line of its own and a list
    of sources instead of the quote lines; the form now comes before and after every result of the reference mode."""
    out = toolsets.with_form([{"type": "text", "text": "«a» — [N-00001, PDF 1], t"}])
    assert out[0]["text"] == toolsets.FORM_HINT and out[-1]["text"] == toolsets.FORM_END and len(out) == 3


def test_a_reference_search_waits_for_the_models_being_loaded(monkeypatch):
    """Qwen's first question went by words only while a new service loaded its models: the reference mode waits."""
    import threading

    from assistant_x.server import mcp_server

    class Lib:
        no_wait, dense_error, _reranker = True, None, None
        dense_ready = threading.Event()

        def may_rerank(self):
            return True

    lib = Lib()
    monkeypatch.setattr(mcp_server, "lib", lambda: lib)
    threading.Timer(0.3, lambda: (lib.dense_ready.set(), setattr(lib, "_reranker", object()))).start()
    import time

    t = time.monotonic()
    mcp_server.wait_models(5)
    assert lib.dense_ready.is_set() and lib._reranker is not None and time.monotonic() - t < 3
    lib.dense_ready.clear()
    lib.dense_error = "no model"
    t = time.monotonic()
    mcp_server.wait_models(5)
    assert time.monotonic() - t < 1  # a model that failed is not waited for
