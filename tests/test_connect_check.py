# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""connect --check reads the answer of its search: a server that answers by words only because a model is missing
(the live test of 0.5: the service of an app outside the Store package of Claude Desktop found no model) is not "in
order"; one whose model is still loading is."""

import sys, textwrap

from assistant_x.clients import connect

SERVER = textwrap.dedent(
    """
    import json, sys
    ANSWER = sys.argv[1]
    for raw in sys.stdin:
        m = json.loads(raw)
        if "id" not in m:
            continue
        if m["method"] == "initialize":
            r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "x", "version": "0"}}
        elif m["method"] == "tools/list":
            r = {"tools": [{"name": "search_library", "inputSchema": {"type": "object"}}]}
        else:
            r = {"content": [{"type": "text", "text": ANSWER}]}
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
    """
)


def entry(tmp_path, answer):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    return {"command": sys.executable, "args": [str(script), answer]}


def test_words_only_for_want_of_a_model_is_a_failure(tmp_path):
    skill = "Before the answer, tell the user: their uploaded skill is of an older version. " * 4
    missing = skill + 'Found by words only: no embedding model (folder ..\\models\\bge-m3). Run "assistant-x doctor".'
    r = connect.probe(entry(tmp_path, missing))
    assert not r["ok"] and "by words only" in r["error"] and "no embedding model" in r["error"]
    loading = "Found by words only: the meaning model is loading (10-20 s).\n\n[N-00001, PDF 2] ..."
    assert connect.probe(entry(tmp_path, loading))["ok"]
    assert connect.probe(entry(tmp_path, "[N-00001, PDF 2] Title (standard)"))["ok"]


def test_check_json_gives_a_fix_for_every_failed_app(monkeypatch, capsys):
    """--check --json: stdout is one JSON document; a failed app carries the code and the command that fixes it."""
    import json

    from assistant_x import clients as K

    class App:
        def __init__(self, name, entry):
            self.NAME, self.TITLE, self._entry = name, name.upper(), entry

        def read(self):
            return self._entry

    apps = {"lmstudio": App("lmstudio", {"command": "x"}), "codex": App("codex", None), "dsh": App("dsh", {"command": "y"})}
    monkeypatch.setattr(K, "app", lambda name: apps[name])
    monkeypatch.setattr(connect, "choose", lambda names: list(names))
    answers = {
        "x": {"ok": False, "error": "the search answers by words only: no embedding model"},
        "y": {"ok": False, "error": "no answer to initialize in 240 s"},
    }
    monkeypatch.setattr(connect, "probe", lambda e: dict(answers[e["command"]]))
    rc = connect.main(["--check", "--json", "lmstudio", "codex", "dsh"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["lmstudio"]["problem"]["code"] == "search-words-only"
    assert out["codex"]["problem"] == {
        "code": "app-not-connected",
        "message": out["codex"]["problem"]["message"],
        "fix": "assistant-x connect codex",
    }
    assert out["dsh"]["problem"]["fix"].startswith("assistant-x connect --check dsh --json")
