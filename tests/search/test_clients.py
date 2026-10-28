# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x connect on a temporary home: the settings of Codex (TOML), DeepSeek Harness (YAML), LM Studio and Claude
Desktop (JSON) get a correct entry; the entries and comments of others stay; a second run changes nothing; disconnect
gives the file back; a file that cannot be read is left alone; the skills are stamped, kept when edited by hand."""

import json, os, sys, tomllib

import pytest

from assistant_x import clients as K
from assistant_x.clients import codex, connect, dsh, lmstudio, skills
from assistant_x.setup import skill

CODEX = """# my settings
model = "o4"  # the model I use

[mcp_servers.other]  # keep me
command = "node"
args = ["srv.js"]

[profiles.fast]
model = "o4-mini"
"""

DSH = """# Your patch layer for this dsh profile
- id: ui-chat
  name: "@deepseek-ai/dsh-client-ui-chat"
  config:
    transcriptView: standard
- id: mcp-time
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: time
    transport: stdio
    command: uvx
    args: ['mcp-server-time']
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(K, "home", lambda: h)
    for var in ("CODEX_HOME", "DSH_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APPDATA", str(h / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(h / "AppData" / "Local"))
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("AX_WORKSPACE", str(tmp_path / "My Library"))
    return h


def entry(toolset="all", compact=False):
    return K.entry(r"C:\Program Files\AX's\python.exe", toolset, compact)


def test_codex_toml_keeps_the_rest_and_comes_back(home):
    p = home / ".codex" / "config.toml"
    p.parent.mkdir()
    p.write_text(CODEX, encoding="utf-8")
    assert codex.connect(entry(), False) == [(str(p), "written")]
    text = p.read_text(encoding="utf-8")
    conf = tomllib.loads(text)
    ours = conf["mcp_servers"]["assistant-x"]
    assert ours["command"] == r"C:\Program Files\AX's\python.exe" and ours["args"][:2] == ["-m", "assistant_x.server.bridge"]
    assert ours["startup_timeout_sec"] >= 60 and ours["env"]["AX_WORKSPACE"].endswith("My Library")
    assert conf["mcp_servers"]["other"]["command"] == "node" and conf["profiles"]["fast"]["model"] == "o4-mini"
    assert "# keep me" in text and "# the model I use" in text and "enabled_tools" not in text
    assert codex.connect(entry(), False) == [(str(p), "unchanged")]  # idempotent
    codex.connect(entry("reader"), False)  # replaced in place, with the reading tools only
    reader = tomllib.loads(p.read_text(encoding="utf-8"))["mcp_servers"]["assistant-x"]
    assert "--tools" in reader["args"] and "library_guide" in reader["enabled_tools"]
    assert p.read_text(encoding="utf-8").count("[mcp_servers.assistant-x]") == 1
    assert codex.read()["command"] == ours["command"]
    assert codex.disconnect(False) == [(str(p), "written")]
    assert p.read_text(encoding="utf-8") == CODEX  # given back as it was
    assert len(list(p.parent.glob("config.backup-*.toml"))) <= K.BACKUPS_KEPT


def test_codex_new_file_and_a_broken_one(home):
    p = home / ".codex" / "config.toml"
    codex.connect(entry(), False)
    assert tomllib.loads(p.read_text(encoding="utf-8"))["mcp_servers"]["assistant-x"]
    p.write_text("model = \n[broken", encoding="utf-8")
    [(path, status)] = codex.connect(entry(), False)
    assert status.startswith("left alone") and "[mcp_servers.assistant-x]" in status
    assert p.read_text(encoding="utf-8") == "model = \n[broken"


def test_dsh_yaml_keeps_the_patches_of_others(home):
    yaml = pytest.importorskip("yaml")
    p = home / ".dsh" / "cordis.patch.yml"
    p.parent.mkdir()
    p.write_text(DSH, encoding="utf-8")
    assert dsh.connect(entry("reader"), False) == [(str(p), "written")]
    patches = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert [x.get("id") for x in patches[:2]] == ["ui-chat", "mcp-time"]
    [ins] = patches[2]["insert"]
    assert ins["name"] == "@deepseek-ai/dsh-mcp-client" and ins["config"]["serverName"] == "assistant-x"
    assert ins["config"]["transport"] == "stdio" and ins["config"]["command"] == r"C:\Program Files\AX's\python.exe"
    assert ins["config"]["args"][-2:] == ["--tools", "reader"] and ins["config"]["env"]["PYTHONUTF8"] == "1"
    assert dsh.read() == entry("reader")
    assert dsh.connect(entry("reader"), False) == [(str(p), "unchanged")]
    assert dsh.disconnect(False) == [(str(p), "written")] and p.read_text(encoding="utf-8") == DSH


def test_dsh_empty_array_new_file_and_a_foreign_entry(home):
    yaml = pytest.importorskip("yaml")
    p = home / ".dsh" / "cordis.patch.yml"
    p.parent.mkdir()
    p.write_text("# empty\n[]\n", encoding="utf-8")
    dsh.connect(entry(), False)
    assert yaml.safe_load(p.read_text(encoding="utf-8"))[0]["insert"][0]["id"] == "mcp-assistant-x"
    dsh.disconnect(False)
    assert yaml.safe_load(p.read_text(encoding="utf-8")) == []
    p.unlink()
    dsh.connect(entry(), False)
    assert len(yaml.safe_load(p.read_text(encoding="utf-8"))) == 1
    p.write_text("- id: mine\n  config:\n    serverName: assistant-x\n", encoding="utf-8")
    [(_, status)] = dsh.connect(entry(), False)
    assert status.startswith("left alone") and "did not write" in status


def test_lmstudio_json(home):
    p = home / ".lmstudio" / "mcp.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"mcpServers": {"hf": {"url": "https://example.org/mcp"}}}), encoding="utf-8")
    assert lmstudio.found()
    e = K.entry(sys.executable, lmstudio.TOOLSET, lmstudio.COMPACT)
    lmstudio.connect(e, False)
    conf = json.loads(p.read_text(encoding="utf-8"))
    assert conf["mcpServers"]["hf"] == {"url": "https://example.org/mcp"}
    assert conf["mcpServers"]["assistant-x"]["args"][-3:] == ["--tools", "reader", "--compact"]
    assert lmstudio.connect(e, False)[0][1] == "unchanged"
    lmstudio.disconnect(False)
    assert json.loads(p.read_text(encoding="utf-8")) == {"mcpServers": {"hf": {"url": "https://example.org/mcp"}}}


def test_claude_desktop_left_alone_when_unreadable(home):
    d = home / "AppData" / "Roaming" / "Claude"
    if os.name != "nt":
        d = home / ".config" / "Claude"
    d.mkdir(parents=True)
    (d / "claude_desktop_config.json").write_text("{not json", encoding="utf-8")
    from assistant_x.clients import claude_desktop

    [(path, status)] = claude_desktop.connect(entry(), False)
    assert status.startswith("left alone") and '"assistant-x"' in status
    assert (d / "claude_desktop_config.json").read_text(encoding="utf-8") == "{not json"
    (d / "claude_desktop_config.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    assert claude_desktop.connect(entry(), False)[0][1] == "written" and claude_desktop.read()["command"]


def test_auto_takes_the_apps_found_and_the_skills(home, monkeypatch):
    (home / ".dsh").mkdir()
    (home / ".lmstudio").mkdir()
    monkeypatch.setattr("shutil.which", lambda name: None)  # no claude, no codex on the PATH
    if os.name != "nt":
        monkeypatch.setattr(K.app("claude_desktop"), "found", lambda: False)
    else:
        monkeypatch.setattr(K.app("claude_desktop"), "found", lambda: False)
    done = connect.connect(["auto"], python=sys.executable, say=lambda s: None)
    assert sorted(done) == ["dsh", "lmstudio"]
    skill_file = home / ".dsh" / "skills" / "assistant-x" / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    assert "Claude" not in text and skill.stamped(text) == (skill.stamped(text)[0], True)
    rows = {r["app"]: r for r in connect.listing()}
    assert rows["dsh"]["connected"] and rows["dsh"]["tools"] == "reader" and rows["lmstudio"]["compact"]
    assert not rows["codex"]["found"] and rows["dsh"]["through_service"]
    skill_file.write_text(text + "\nMy own rule.\n", encoding="utf-8")  # edited by hand: kept
    assert skills.state("dsh") == "edited"
    assert "kept" in skills.install("dsh")[0][1] and (skill_file.parent / "SKILL.md.new").exists()
    connect.disconnect(["dsh"], say=lambda s: None)
    assert skill_file.read_text(encoding="utf-8").endswith("My own rule.\n") and dsh.read() is None


def test_an_outdated_skill_is_updated(home, monkeypatch):
    (home / ".dsh").mkdir()
    skills.install("dsh")
    p = home / ".dsh" / "skills" / "assistant-x" / "SKILL.md"
    import assistant_x

    monkeypatch.setattr(assistant_x, "__version__", "9.9")
    assert skills.state("dsh") == "outdated" and skills.install("dsh")[0][1] == "skill updated"
    assert "assistant-x skill 9.9 " in p.read_text(encoding="utf-8")
    assert skills.remove("dsh")[0][1] == "skill taken out" and not p.parent.exists()


def test_claude_code_through_its_command_line(home, monkeypatch):
    from assistant_x.clients import claude_code

    calls = []
    monkeypatch.setattr(claude_code, "exe", lambda: "claude")
    monkeypatch.setattr(claude_code, "claude", lambda *a: calls.append(a) or (0, ""))
    assert claude_code.connect(entry(), False)[0][1] == "written"
    add = calls[-1]
    assert add[:2] == ("mcp", "add-json") and add[-2:] == ("-s", "user") and json.loads(add[3])["type"] == "stdio"
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"assistant-x": json.loads(add[3])}}), encoding="utf-8")
    assert claude_code.connect(entry(), False)[0][1] == "unchanged"


def test_skill_variants_from_one_core():
    claude, agent, guide = skill.render("general", "claude"), skill.render("general", "agent"), skill.guide("general")
    safety = (skill.TEMPLATES / "safety.md").read_text(encoding="utf-8").strip()
    for text in (claude, agent, guide):
        assert safety in text  # one text of the safety rules
    assert "Claude" in claude and "Claude" not in agent and "Claude" not in guide
    assert skill.stamped(agent)[1] and skill.stamped(claude)[1] and not skill.stamped(agent + "x")[1]
    assert agent.startswith("---\nname:") and "\n---\n<!-- assistant-x skill " in agent


def test_the_entry_runs_without_a_window(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    want = "pythonw.exe" if os.name == "nt" else "python.exe"
    assert K.windowless(str(exe)).endswith(want) and K.windowless("/usr/bin/python3") == "/usr/bin/python3"


def test_check_through_a_connected_app(home, mini, tmp_path, monkeypatch):
    """connect --check starts the entry as the app does: the handshake, the tool list and a search."""
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.setenv("AX_MCP_LOCK_FILE", str(tmp_path / "mcp.lock"))
    monkeypatch.setenv("AX_SERVICE_PORT", "0")
    (home / ".lmstudio").mkdir()
    connect.connect(["lmstudio"], python=sys.executable, root=mini["root"], say=lambda s: None)
    try:
        r = connect.check(["lmstudio"], say=lambda s: None)["lmstudio"]
        assert r["ok"] and r["tools"] == 8 and r["initialize_s"] < 5, r
    finally:
        from assistant_x.server import service
        import psutil

        info = service.read_info(mini["root"])
        if info:
            psutil.Process(info["pid"]).kill()
