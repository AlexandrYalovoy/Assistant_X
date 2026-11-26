# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import json
import runpy
from pathlib import Path

import pytest

from assistant_x.search import context, jurisdiction
from assistant_x.server import bridge, intake_tools, mcp_server as server
from tests.search.test_protocol import called


@pytest.fixture
def reader(lib, monkeypatch):
    monkeypatch.setattr(server, "_lib", lib)
    monkeypatch.setattr(server, "_owner", object())
    return lib


def test_ranges_and_malformed_references(reader):
    for dash in ("-", "–", "—"):
        result = server.verify_answer(f"[N-00001, PDF 1{dash}2]")
        assert result["ok"] and [r["pdf_page"] for r in result["references"]] == [1, 2]
    assert not server.verify_answer("[N-00001, PDF 1] [N-00001, PDF 2")["ok"]
    for bad in ("PDF 99, PDF 1", "PDF ?", "PDF 2-1", "PDF 1-", "PDF 1-99"):
        assert not server.verify_answer(f"[N-00001, PDF 1] [N-00001, {bad}]")["ok"]


def test_budget_and_quality_on_expanded_pages(reader, monkeypatch):
    hit = dict(code="N-00001", page=2, text="target", title="Test")
    monkeypatch.setattr(server, "find_fragments", lambda *args, **kw: [hit])
    monkeypatch.setattr(reader, "page_text", lambda *args: "other data\n" * 300 + "target 17 m/s\n" + "more data\n" * 300)
    monkeypatch.setattr(reader, "page_info", lambda c, a, b: {a: (None, 95, "complex_table,garbled")})
    result = context.build("target", 3, 3, 2000)
    assert result["page_chars"] == sum(len(p["text"]) for p in result["pages"]) <= 2000
    assert all(p["truncated"] and "target 17 m/s" in p["text"] for p in result["pages"])
    assert all("complex table" in p["page_note"] and "garbled" in p["page_note"] for p in result["pages"] if p["expanded"])


def test_one_long_ocr_line_retains_the_matched_value():
    body = "noise " * 500 + "velocity 12 m/s" + " more" * 500
    for hit in ("velocity 12 m/s", body):
        assert "velocity 12 m/s" in context.excerpt("velocity", body, hit, 120)


def test_key_norm_reports_quality_of_the_actual_page(reader, monkeypatch):
    from assistant_x.search import key_norms

    import sqlite3
    from types import SimpleNamespace

    con = sqlite3.connect(":memory:")
    reader.con.backup(con)
    con.row_factory = sqlite3.Row
    monkeypatch.setattr(server, "lib", lambda: SimpleNamespace(cfg=reader.cfg, con=con))
    try:
        con.execute("UPDATE pages SET flags='garbled,complex_table',ocr_score=25 WHERE code='N-00001' AND page=2")
        monkeypatch.setattr(key_norms, "entries_for", lambda data, q: [dict(code="N-00001", pdf_page=2, quote="test")])
        con.execute(
            "UPDATE docs SET card=json_set(card,'$.doc.applicability_source', 'Approval A, clause 2') WHERE code='N-00001'"
        )
        hit = server.key_hits("test")[0]
        assert hit["applicability_source"] == "Approval A, clause 2"
        assert "complex table" in hit["page_note"] and "garbled" in hit["page_note"] and "25" in hit["page_note"]
    finally:
        con.close()


def test_single_call_and_permissions(reader, monkeypatch):
    monkeypatch.setattr(server, "ACTIVE_TOOLSET", "one_intake")
    assert "No command" in server.library("library_remove")
    assert "No command" in server.library("base_install")
    out = called("library", {"action": "answer_context", "args": {"query": "GOST", "mode": "fast"}})
    assert json.loads(out.content[0].text)["limits"]["pages"] == 1
    b = bridge.Bridge(toolset="one_intake", out=io.BytesIO())
    b.lists.add(1)
    b.adjust({"id": 1, "result": {"tools": [{"name": "base_remove"}]}})
    assert b.toolset == "one_intake"
    sent = []
    b.forward = sent.append
    for action in ("intake_status", "base_remove"):
        b.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "library", "arguments": {"action": action}},
            }
        )
    assert len(sent) == 1 and b"No command" in b.out.getvalue()


def test_optional_formats_are_per_run(monkeypatch):
    captured = []
    monkeypatch.setattr(intake_tools, "_job", lambda _: None)
    monkeypatch.setattr(intake_tools, "_alive", lambda _: False)
    monkeypatch.setattr(intake_tools, "_start", lambda k, cmd, **kw: (captured.append(cmd) is None, "ok"))
    intake_tools.run(include=["spreadsheets", "web_pages"])
    assert captured[0][-4:] == ["--spreadsheets", "include", "--web-pages", "include"]
    intake_tools.run(include=["other"])
    assert len(captured) == 1


def test_selected_pages_keep_search_metadata_without_duplicate_text():
    result = dict(
        matches=[dict(code="N", pdf_page=2, text="", heading="Pressure", references=[["table", 3]])],
        pages=[dict(code="N", pdf_page=2, text="actual evidence", truncated=True)],
    )
    out = context.for_agent(result)
    assert not out["matches"]
    assert out["pages"][0]["text"] == "actual evidence"
    assert out["pages"][0]["references"] == [["table", 3]]
    assert result["matches"] and "heading" not in result["pages"][0]


def test_country_override_and_unknown():
    jur = jurisdiction.load("oil-gas-ru")
    rows = [{"jurisdiction": "RU"}, {"jurisdiction": "KZ"}]
    assert jur.arrange(rows, "pipeline", 2, "KZ")[0] == rows[1]
    assert jur.arrange(rows, "pipeline", 2, "RU")[0] == rows[0]
    assert jur.arrange(rows, "API", 2, "KZ") == rows
    assert not jur.of({"title": "Undesignated standard"})


def test_benchmark_requires_evidence_on_the_correct_page():
    bench = runpy.run_path(str(Path(__file__).parents[1] / "golden" / "context_cost.py"))
    item = {"expect": [["N-00001", [2]]], "values": ["5 m"]}
    page = {"code": "N-00001", "pdf_page": 2, "text": "15 mm"}
    out = {"query": "5 m", "matches": [page], "pages": [dict(page, code="N-00002", text="5 m")]}
    assert bench["score"](item, out) == dict(pages=1, read=0, pages_of=1, values=0, values_of=1)
    out["pages"].append(page)
    assert bench["score"](item, out)["values"] == 0
    for different in ("0.5 m", "5 m/s", "5.2 m"):
        page["text"] = different
        assert bench["score"](item, out)["values"] == 0
    page["text"] = "height 5 m"
    assert bench["score"](item, out)["values"] == 1
    trial = dict(
        id="1",
        client="Codex",
        model="test",
        library_version="1",
        route="single",
        mode="balanced",
        correct=True,
        calls=1,
        seconds=2,
        output=30,
    )
    report = bench["summarize_trials"]([trial, dict(trial, correct=False)])[0]
    assert report["output_per_correct"] == 60 and report["cost_usd"] is None
