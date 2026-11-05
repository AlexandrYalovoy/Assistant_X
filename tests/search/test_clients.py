# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x connect on a temporary home: the settings of Codex (TOML), DeepSeek Harness (YAML), LM Studio and Claude
Desktop (JSON) get a correct entry; the entries and comments of others stay; a second run changes nothing; disconnect
gives the file back; a file that cannot be read is left alone; the skills are stamped, kept when edited by hand."""

import json, os, sys, tomllib

import pytest

from assistant_x import clients as K
from assistant_x.clients import codex, connect, dsh, lmstudio, skills
from assistant_x.server import toolsets
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
    for var in ("CODEX_HOME", "DSH_HOME", "XDG_CONFIG_HOME"):  # XDG: Cline on Linux, never the real ~/.config
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


CODEX_SERVER_KEYS = {  # the keys of a stdio server in Codex's config reference (codex-cli 0.165.0)
    "command",
    "args",
    "env",
    "cwd",
    "startup_timeout_sec",
    "tool_timeout_sec",
    "enabled",
    "enabled_tools",
    "disabled_tools",
    "default_tools_approval_mode",
    "tools",
}


def test_codex_entry_uses_only_keys_codex_knows(home):
    """The entry is a [mcp_servers.<name>] table (not mcpServers) of keys Codex documents, with string args and env."""
    codex.connect(entry("reader", True), False)
    data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    ours = data["mcp_servers"]["assistant-x"]
    assert set(ours) <= CODEX_SERVER_KEYS and "mcpServers" not in data
    assert isinstance(ours["command"], str) and all(isinstance(a, str) for a in ours["args"])
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in ours["env"].items())
    assert ours["startup_timeout_sec"] >= 30 and ours["tool_timeout_sec"] >= 600


@pytest.mark.skipif(not os.environ.get("AX_CODEX_CLI"), reason="AX_CODEX_CLI names a Codex CLI to check against")
def test_the_real_codex_cli_reads_the_entry_and_the_marketplace(home, tmp_path):
    """With a real Codex CLI (no sign-in needed): codex mcp list shows the entry enabled, and our marketplace of this
    repository is accepted with its plugin. CODEX_HOME is a temporary folder: the user's settings are not touched."""
    import subprocess

    cli = os.environ["AX_CODEX_CLI"]
    env = dict(os.environ, CODEX_HOME=str(home / ".codex"))
    codex.connect(entry(), False)
    run = lambda *a: subprocess.run([cli, *a], env=env, capture_output=True, text=True, timeout=120)  # noqa: E731
    listed = run("mcp", "list")
    assert listed.returncode == 0 and "assistant-x" in listed.stdout and "enabled" in listed.stdout, listed
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    added = run("plugin", "marketplace", "add", repo)
    assert added.returncode == 0, added
    plugins = run("plugin", "list")
    assert "assistant-x@assistant-x" in plugins.stdout, plugins


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
    assert conf["mcpServers"]["assistant-x"]["args"][-3:] == ["--tools", "one", "--compact"]
    assert lmstudio.connect(e, False)[0][1] == "unchanged"
    lmstudio.disconnect(False)
    assert json.loads(p.read_text(encoding="utf-8")) == {"mcpServers": {"hf": {"url": "https://example.org/mcp"}}}


def test_gemini_cli_settings_and_rules(home):
    from assistant_x.clients import gemini

    d = home / ".gemini"
    d.mkdir()
    (d / "settings.json").write_text(json.dumps({"theme": "dark", "mcpServers": {"git": {"command": "uvx"}}}), "utf-8")
    (d / "GEMINI.md").write_text("# My rules\n\nAnswer briefly.\n", encoding="utf-8")
    assert gemini.found() and "gemini" in K.APPS
    e = entry()
    assert [s for _, s in gemini.connect(e, False)] == ["written", "written"]
    conf = json.loads((d / "settings.json").read_text(encoding="utf-8"))
    ours = conf["mcpServers"]["assistant-x"]
    assert conf["theme"] == "dark" and conf["mcpServers"]["git"] == {"command": "uvx"}
    assert ours["timeout"] == K.TOOL_TIMEOUT * 1000 and ours["trust"] is False and ours["command"] == e["command"]
    rules = (d / "GEMINI.md").read_text(encoding="utf-8")
    assert rules.startswith("# My rules\n\nAnswer briefly.\n") and gemini.BEGIN in rules and "library_guide" in rules
    assert [s for _, s in gemini.connect(e, False)] == ["unchanged", "unchanged"]
    gemini.disconnect(False)
    assert "assistant-x" not in json.loads((d / "settings.json").read_text(encoding="utf-8"))["mcpServers"]
    assert (d / "GEMINI.md").read_text(encoding="utf-8") == "# My rules\n\nAnswer briefly.\n"


def test_kimi_cli_and_kimi_code_settings_and_rules(home, monkeypatch):
    """Kimi: ~/.kimi/mcp.json and the folder of Kimi Code (KIMI_CODE_HOME), each with the rules in its AGENTS.md;
    Kimi Code takes the timeouts in ms. The formats from the documentation of Moonshot AI, not a running Kimi."""
    from assistant_x.clients import kimi

    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    assert not kimi.found() and "kimi" in K.APPS and kimi.read() is None
    cli, code = home / ".kimi", home / "kimi-code-home"
    cli.mkdir()
    code.mkdir()
    monkeypatch.setenv("KIMI_CODE_HOME", str(code))
    (cli / "mcp.json").write_text(json.dumps({"mcpServers": {"git": {"command": "uvx"}}}), encoding="utf-8")
    (code / "AGENTS.md").write_text("# Mine\n", encoding="utf-8")
    e = entry()
    assert kimi.found() and [s for _, s in kimi.connect(e, False)] == ["written"] * 4
    a = json.loads((cli / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    b = json.loads((code / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["assistant-x"]
    assert a["git"] == {"command": "uvx"} and a["assistant-x"]["command"] == e["command"]
    assert "startupTimeoutMs" not in a["assistant-x"] and b["toolTimeoutMs"] == K.TOOL_TIMEOUT * 1000
    assert b["startupTimeoutMs"] == K.STARTUP_TIMEOUT * 1000 and kimi.read()["command"] == e["command"]
    rules = (code / "AGENTS.md").read_text(encoding="utf-8")
    assert rules.startswith("# Mine\n\n") and kimi.BEGIN in rules and "library_guide" in rules
    assert [s for _, s in kimi.connect(e, False)] == ["unchanged"] * 4
    kimi.disconnect(False)
    assert json.loads((cli / "mcp.json").read_text(encoding="utf-8")) == {"mcpServers": {"git": {"command": "uvx"}}}
    assert (code / "AGENTS.md").read_text(encoding="utf-8") == "# Mine\n" and not (cli / "AGENTS.md").read_text("utf-8")


@pytest.mark.parametrize("name", ["antigravity", "cursor", "cline"])
def test_the_mcp_json_of_ide_agents(home, name):
    a = K.app(name)
    assert not a.found() and a.read() is None
    path = __import__("pathlib").Path(a.configs()[0])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "node", "args": ["x.js"]}}}), encoding="utf-8")
    assert a.found()
    e = entry(a.TOOLSET, a.COMPACT)
    assert a.connect(e, False)[0][1] == "written"
    conf = json.loads(path.read_text(encoding="utf-8"))
    ours = conf["mcpServers"]["assistant-x"]
    assert conf["mcpServers"]["other"] == {"command": "node", "args": ["x.js"]} and ours["env"]["PYTHONUTF8"] == "1"
    assert a.read()["args"] == e["args"] and a.connect(e, False)[0][1] == "unchanged"
    if name == "cline":  # a long first answer, the tools not approved in advance
        assert ours["timeout"] == K.TOOL_TIMEOUT and ours["disabled"] is False and ours["autoApprove"] == []
    a.disconnect(False)
    assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": {"other": {"command": "node", "args": ["x.js"]}}}


def test_claude_desktop_left_alone_when_unreadable(home):
    d = home / "AppData" / "Roaming" / "Claude"
    if os.name != "nt":
        d = home / ".config" / "Claude"
    d.mkdir(parents=True)
    (d / "claude_desktop_config.json").write_text("{not json", encoding="utf-8")
    from assistant_x.clients import claude_desktop

    (path, status), _ = claude_desktop.connect(entry(), False)
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
    assert rows["dsh"]["connected"] and rows["dsh"]["tools"] == "one" and rows["lmstudio"]["compact"]
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


def test_claude_code_allows_the_reading_tools_in_advance(home, monkeypatch):
    from assistant_x.clients import claude_code

    monkeypatch.setattr(claude_code, "exe", lambda: "claude")
    monkeypatch.setattr(claude_code, "claude", lambda *a: (0, ""))
    p = home / ".claude" / "settings.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["Bash(git push:*)"]}}), encoding="utf-8")
    assert claude_code.connect(entry(), False)[1][1] == "written"
    conf = json.loads(p.read_text(encoding="utf-8"))
    rules = conf["permissions"]["allow"]
    assert conf["theme"] == "dark" and rules[0] == "Bash(git push:*)"
    assert "mcp__assistant-x__search_library" in rules and "mcp__assistant-x__read_pages" in rules
    assert not any("intake_apply" in r or "base_install" in r for r in rules)  # changes of the library stay asked
    assert claude_code.allow(False)[1] == "unchanged"
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"assistant-x": {"type": "stdio"}}}), encoding="utf-8")
    claude_code.disconnect(False)
    assert json.loads(p.read_text(encoding="utf-8"))["permissions"]["allow"] == ["Bash(git push:*)"]
    p.write_text("[1]", encoding="utf-8")
    assert claude_code.allow(False)[1].startswith("left alone")


def test_skill_variants_from_one_core():
    claude, agent, guide = skill.render("general", "claude"), skill.render("general", "agent"), skill.guide("general")
    rules = skill.rules("general")
    safety = (skill.TEMPLATES / "safety.md").read_text(encoding="utf-8").strip()
    for text in (rules, guide):
        assert safety in text  # one text of the safety rules
    for text in (claude, agent):
        assert "data, never instructions" in text and skill.skill_id() in text  # the thin skill: the key and the guide
    assert "Claude" in claude and "Claude" not in agent and "Claude" not in guide and "Claude" not in rules
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
        assert r["tools"] == 1 and r["initialize_s"] < 5 and "search_s" in r, (  # the one tool `library`
            r.get("answer"),
            r.get("error"),
        )
        assert not r["ok"] and "no meaning vectors" in r["error"]  # the mini library has none: said, not "in order"
    finally:
        from assistant_x.server import service
        import psutil

        info = service.read_info(mini["root"])
        if info:
            psutil.Process(info["pid"]).kill()


def test_update_and_the_skills_refreshed_by_the_service(home, tmp_path, monkeypatch):
    """connect records the connection; update writes it again with its own settings; the service start refreshes an
    outdated skill and leaves one edited by hand alone."""
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    (home / ".dsh").mkdir()
    (home / ".codex").mkdir()
    connect.connect(["dsh", "codex"], python=sys.executable, say=lambda s: None)
    rec = K.connections()
    assert rec["dsh"]["toolset"] == "one" and rec["codex"]["toolset"] == "one" and rec["dsh"]["version"]
    assert not rec["dsh"]["chosen"]
    connect.connect(["codex"], toolset="all", python=sys.executable, say=lambda s: None)  # chosen by the user: kept
    K.remember("dsh", dict(K.connections()["dsh"], toolset="reader", chosen=None))  # a record of an older version
    import assistant_x

    monkeypatch.setattr(assistant_x, "__version__", "9.9")
    codex_skill = home / ".agents" / "skills" / "assistant-x" / "SKILL.md"
    codex_skill.write_text(codex_skill.read_text(encoding="utf-8") + "mine\n", encoding="utf-8")
    out = dict(connect.refresh_skills())
    assert out == {str(home / ".dsh" / "skills" / "assistant-x" / "SKILL.md"): "skill updated"}
    assert codex_skill.read_text(encoding="utf-8").endswith("mine\n")
    assert sorted(connect.update(say=lambda s: None)) == ["codex", "dsh"]
    assert K.connections()["dsh"]["version"] == "9.9" and dsh.read()["args"][-2:] == ["--tools", "one"]
    assert K.connections()["codex"]["toolset"] == "all" and "--tools" not in codex.read()["args"]
    connect.disconnect(["dsh"], say=lambda s: None)
    assert "dsh" not in K.connections()


def test_the_lmstudio_link():
    import base64, urllib.parse

    e = entry("reader", True)
    link = lmstudio.link(e)
    assert link.startswith("lmstudio://add_mcp?name=assistant-x&config=")
    config = urllib.parse.unquote(link.split("config=", 1)[1])
    assert json.loads(base64.b64decode(config)) == e


def test_claude_desktop_hears_once_that_its_skill_is_outdated(tmp_path, monkeypatch):
    """The uploaded skill of Claude Desktop cannot be refreshed: the start notice of the server asks for a new upload
    when the skill of the workspace is of an older version; none when it is current or missing."""
    from assistant_x.server import mcp_server

    ws = tmp_path / "ws"
    (ws / "skill").mkdir(parents=True)
    (ws / "assistant_x.toml").write_text('profile = "general"\n', encoding="utf-8")
    monkeypatch.setenv("AX_WORKSPACE", str(ws))
    assert mcp_server.desktop_skill_note() == []
    p = ws / "skill" / "SKILL.md"
    p.write_text(skill.render("general"), encoding="utf-8")
    assert mcp_server.desktop_skill_note() == []
    p.write_text("---\nname: x\n---\nold skill\n", encoding="utf-8")
    [note] = mcp_server.desktop_skill_note()
    assert "before 0.4" in note and "upload it again" in note
    # only Claude Desktop hears it (the shared service answers LM Studio and the others too), and once
    monkeypatch.setattr(mcp_server, "_noticed", True)
    monkeypatch.setattr(mcp_server, "_desktop_noticed", False)
    assert mcp_server.start_notice("lms-loop") == "" and mcp_server.start_notice("") == ""
    assert "upload it again" in mcp_server.start_notice("claude-ai") and mcp_server.start_notice("claude-ai") == ""


# ---------- the Claude Desktop of the installer, a rules file not in UTF-8 (audit of 2026-11-03) ----------


def test_the_installer_records_claude_desktop_and_update_moves_it(home, tmp_path, monkeypatch):
    """I-01: the installer connects Claude Desktop and records it in connections.json, so assistant-x update (and
    update --from) moves it to the python of the new version; an older install with the entry alone is moved too."""
    from assistant_x.clients import claude_desktop
    from assistant_x.setup import install

    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    lib = str(tmp_path / "My Library")
    monkeypatch.setattr(install.P, "ROOT", lib, raising=False)
    monkeypatch.setattr(install, "say", lambda s="": None)
    old = r"C:\OLD\venv\Scripts\python.exe"
    (home / "AppData" / "Roaming" / "Claude").mkdir(parents=True)
    install.register_desktop(old, False)
    assert K.connections()["claude_desktop"]["toolset"] == "one"  # the one tool: one question (colleague test 2026-11-04)
    assert claude_desktop.read()["command"] == old and claude_desktop.read()["args"][-2:] == ["--tools", "one"]
    assert list(connect.update(say=lambda s: None)) == ["claude_desktop"]
    assert claude_desktop.read()["command"] == K.windowless(sys.executable)
    K.remember("claude_desktop", None)  # an install before the record: the entry in the settings alone
    claude_desktop.connect(K.entry(old, "all", False, lib), False)
    assert K.connections() == {} and list(connect.update(say=lambda s: None)) == ["claude_desktop"]
    e = claude_desktop.read()
    assert e["command"] == K.windowless(sys.executable) and e["env"]["AX_WORKSPACE"] == lib
    assert K.connections()["claude_desktop"]["workspace"] == lib
    assert e["args"][-2:] == ["--tools", "one"]  # an older install with every tool apart moves to the one tool


@pytest.mark.parametrize("app", ["gemini", "kimi"])
def test_a_rules_file_not_in_utf8_is_left_alone(home, tmp_path, monkeypatch, app):
    """I-06: GEMINI.md or AGENTS.md saved in the code page of Windows is left alone with a word to add the rules by
    hand; the entry is written, the file keeps its bytes, disconnect does not fail on it."""
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    folder = home / (".gemini" if app == "gemini" else ".kimi")
    folder.mkdir()
    rules = folder / ("GEMINI.md" if app == "gemini" else "AGENTS.md")
    mine = "\u041c\u043e\u0438 \u043f\u0440\u0430\u0432\u0438\u043b\u0430\n".encode("cp1251")
    rules.write_bytes(mine)
    done = connect.connect([app], python=sys.executable, say=lambda s: None)[app]
    assert (str(rules), "left alone: not UTF-8; add the rules by hand") in done
    assert K.app(app).read() and rules.read_bytes() == mine
    connect.disconnect([app], say=lambda s: None)
    assert rules.read_bytes() == mine and not K.app(app).read()


def test_one_app_that_fails_never_stops_the_installer(home, tmp_path, monkeypatch):
    """I-06: register_others connects every app found; one that raises is reported and the next is still connected."""
    from assistant_x.clients import gemini
    from assistant_x.setup import install

    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    said = []
    monkeypatch.setattr(install, "say", lambda s="": said.append(s))
    monkeypatch.setattr(install.P, "ROOT", str(home / "lib"), raising=False)
    (home / ".gemini").mkdir()
    (home / ".kimi").mkdir()  # after Gemini CLI in the order of the installer
    monkeypatch.setattr(gemini, "connect", lambda e, dry: 1 / 0)
    for n in K.APPS:
        if n not in ("gemini", "kimi"):
            monkeypatch.setattr(K.app(n), "found", lambda: False)
    install.register_others(sys.executable, False)
    assert any("Gemini CLI: not connected (ZeroDivisionError" in s for s in said)
    assert K.app("kimi").read() and list(K.connections()) == ["kimi"]


def test_claude_desktop_allows_the_reading_tools_of_its_code_tab(home, monkeypatch):
    """The author, 2026-11-04: the Code tab of Claude Desktop asked before every search ("no prompt, or one at the first
    start"). Connecting Claude Desktop allows the reading tools in ~/.claude/settings.json (a temporary home here);
    export_references too (no question at all); disconnecting takes the rules out unless Claude Code itself is
    connected."""
    from assistant_x.clients import claude_code, claude_desktop

    d = home / "AppData" / "Roaming" / "Claude" if os.name == "nt" else home / ".config" / "Claude"
    d.mkdir(parents=True)
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text('{"model": "x", "permissions": {"allow": ["Bash(ls)"]}}', "utf-8")
    monkeypatch.setattr(claude_code, "read", lambda: None)
    claude_desktop.connect(entry(), False)
    conf = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    rules = conf["permissions"]["allow"]
    assert conf["model"] == "x" and rules[0] == "Bash(ls)" and set(claude_code.allowed_tools()) <= set(rules)
    assert "mcp__assistant-x__export_references" in rules and "mcp__assistant-x__search_library" in rules
    assert claude_desktop.connect(entry(), False)[-1][1] == "unchanged"
    claude_desktop.disconnect(False)
    assert json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"] == [
        "Bash(ls)"
    ]


def test_lmstudio_asks_no_confirmation_for_the_library(home):
    """The author, 2026-11-04: LM Studio asked before every tool call; connect lists the server in
    chat.skipToolConfirmationPatterns of its settings, the other settings and patterns stay; disconnect takes it out;
    a settings file LM Studio has not written yet is left alone."""
    from assistant_x.clients import lmstudio

    (home / ".lmstudio").mkdir()
    assert lmstudio.skip_confirmation(False)[1].startswith("left alone")
    s = home / ".lmstudio" / "settings.json"
    s.write_text(
        json.dumps({"chat": {"neverAskForToolConfirmation": False, "skipToolConfirmationPatterns": ["mcp/x:a"]}, "y": 1}),
        "utf-8",
    )
    lmstudio.connect(entry("reader", True), False)
    conf = json.loads(s.read_text(encoding="utf-8"))
    assert conf["y"] == 1 and conf["chat"]["skipToolConfirmationPatterns"] == ["mcp/x:a", "mcp/assistant-x:*"]
    assert lmstudio.skip_confirmation(False)[1] == "unchanged"
    lmstudio.disconnect(False)
    assert json.loads(s.read_text(encoding="utf-8"))["chat"]["skipToolConfirmationPatterns"] == ["mcp/x:a"]


def test_one_tool_for_the_chat_of_claude_desktop():
    """The author, 2026-11-04: the chat of Claude Desktop asks once a tool, nine questions at the first use. The set
    "one" is the tool `library` alone; it carries every command by its name and arguments, names a wrong one, and the
    other sets never show it."""
    from assistant_x.clients import claude_desktop
    from assistant_x.server import mcp_server, toolsets

    assert toolsets.allowed("library", "one") and not toolsets.allowed("search_library", "one")
    assert not toolsets.allowed("library", "all") and not toolsets.allowed("library", "reader")
    assert claude_desktop.TOOLSET == "one" and "--tools" in K.entry(toolset="one")["args"]
    assert {"search_library", "page_image", "export_references", "intake_apply"} <= mcp_server.ONE_ACTIONS
    assert "library" not in mcp_server.ONE_ACTIONS
    assert mcp_server.library("nope").startswith("No command 'nope'")
    assert mcp_server.library("search_library", {"qery": "x"}).startswith("search_library takes no qery")
    assert "query" in mcp_server.library("search_library", {"qery": "x"})


def test_a_service_of_older_code_is_asked_to_stop():
    """A running service kept the code of before an update: its /health names its code stamp, a bridge of another
    stamp sends POST /shutdown, and the service exits once no request is in work (no process is killed)."""
    import asyncio

    from assistant_x.server import service

    assert service.code_stamp() == service.code_stamp() and len(service.code_stamp()) == 12
    sent = []

    async def app(scope, receive, send):
        sent.append("app")

    a = service.Activity(app, {"version": "x", "code": "old"})

    async def send(m):
        sent.append(m)

    asyncio.run(a({"type": "http", "path": "/shutdown", "method": "POST"}, None, send))
    assert a.stop and sent[-1]["body"] == b'{"stopping": true}' and "app" not in sent


def test_codex_shows_the_tools_of_its_set(home):
    """Codex hides every tool not in enabled_tools: the set `one` lists `library`, `reader` the reading tools, `all`
    no list."""
    (home / ".codex").mkdir()
    p = home / ".codex" / "config.toml"
    for ts, shown in (("one", ["library"]), ("reader", list(toolsets.READER + toolsets.EXPORT)), ("all", None)):
        codex.connect(entry(ts), False)
        got = tomllib.loads(p.read_text(encoding="utf-8"))["mcp_servers"]["assistant-x"].get("enabled_tools")
        assert got == shown, ts


def test_the_library_takes_its_args_as_a_json_text():
    from assistant_x.server import mcp_server

    assert mcp_server.library("search_library", '{"qery": "x"}').startswith("search_library takes no qery")
    assert mcp_server.library(" nope ").startswith("No command 'nope'")
    assert set(connect_allowed()) >= {"mcp__assistant-x__library", "mcp__assistant-x__search_library"}


def connect_allowed():
    from assistant_x.clients import claude_code

    return claude_code.allowed_tools()


def test_a_bridge_older_than_the_code_on_the_disk_keeps_a_service_of_that_code(monkeypatch):
    """Found 2026-11-04: a bridge started before an update compared a service with its own code and stopped every
    service of the new code, the one it started too, again and again. It compares with the code on the disk now."""
    import http.server
    import threading

    from assistant_x.server import bridge, service

    now = service.disk_stamp()
    stops = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"pid": 7, "code": self.server.code}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            stops.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(service, "code_stamp", lambda: "older-bridge")  # the code this bridge loaded
        b = bridge.Bridge(out=None)
        info = {"pid": 7, "port": srv.server_address[1]}
        srv.code = now
        assert b.healthy(info) and stops == []  # a service of the code on the disk: kept
        srv.code = "older-service"
        assert not b.healthy(info) and stops == ["/shutdown"]  # a service of older code: asked to stop
    finally:
        srv.shutdown()
    assert len(service.disk_stamp()) == 12 and service.disk_stamp() == now


def test_lmstudio_models_load_with_a_context_of_32768(home):
    """The author, 2026-11-04: a model picked in the chat of LM Studio loaded with 8192 and the answers lost their
    quotes. connect sets the default load context of every model in LM Studio's own per-model files, keeps their
    other settings, never lowers a larger one and writes no backup beside them (LM Studio would read it as a model)."""
    lm = home / ".lmstudio"
    (lm / "hub" / "models" / "qwen" / "qwen3.5-9b").mkdir(parents=True)
    (lm / "hub" / "models" / "qwen" / "qwen3.5-9b" / "model.yaml").write_text("x", encoding="utf-8")
    g = lm / "models" / "pub" / "Repo-GGUF"
    g.mkdir(parents=True)
    (g / "Model-Q4.gguf").write_bytes(b"x")
    (g / "mmproj-Model.gguf").write_bytes(b"x")
    base = lm / ".internal" / "user-concrete-model-default-config"
    (base / "pub" / "Repo-GGUF").mkdir(parents=True)
    keep = {"preset": "mine", "operation": {"fields": [{"key": "x", "value": 1}]}, "load": {"fields": []}}
    (base / "pub" / "Repo-GGUF" / "Model-Q4.gguf.json").write_text(json.dumps(keep), encoding="utf-8")
    assert lmstudio.model_keys() == ["qwen/qwen3.5-9b", "pub/Repo-GGUF/Model-Q4.gguf"]
    out = lmstudio.model_context(False)
    assert [s for _, s in out] == ["context 32768", "context 32768"]
    hub = json.loads((base / "qwen" / "qwen3.5-9b.json").read_text(encoding="utf-8"))
    assert hub["load"]["fields"] == [{"key": "llm.load.contextLength", "value": 32768}]
    gguf = json.loads((base / "pub" / "Repo-GGUF" / "Model-Q4.gguf.json").read_text(encoding="utf-8"))
    assert gguf["preset"] == "mine" and gguf["operation"] == keep["operation"]
    assert sorted(p.name for p in (base / "pub" / "Repo-GGUF").iterdir()) == ["Model-Q4.gguf.json"]
    assert lmstudio.model_context(False) == []  # already right: nothing written
    big = {"load": {"fields": [{"key": "llm.load.contextLength", "value": 65536}]}}
    (base / "qwen" / "qwen3.5-9b.json").write_text(json.dumps(big), encoding="utf-8")
    assert lmstudio.model_context(False) == []  # a larger context is the user's: kept


def test_the_thin_skill_and_its_outdated_copy():
    """The author, 2026-11-04: the skill uploaded in Claude Desktop cannot be updated by the program, and an older one
    kept «Independent assessment». The skill only switches the assistant on and calls the guide with its id; the
    guide gives the current rules and says once a session when the id is another one, or when Claude Desktop passes
    none (a skill of before the thin one). A session that never called the guide gets the rules with its first search."""
    from assistant_x.server import mcp_server

    class S:
        pass

    class Ctx:
        def __init__(self, name):
            self.request_context = S()
            self.request_context.session = S()
            self.request_context.session.client_params = S()
            self.request_context.session.client_params.clientInfo = S()
            self.request_context.session.client_params.clientInfo.name = name

    text = skill.render("general", "claude")
    assert len(text) < 5000 and f'"skill": "{skill.skill_id()}"' in text and "Independent" not in text
    desktop, code = Ctx("claude-ai"), Ctx("claude-code")
    assert mcp_server.skill_note(skill.skill_id(), "claude-ai", desktop) == ""
    assert mcp_server.skill_note("0123456789ab", "claude-ai", desktop) == mcp_server.SKILL_OUTDATED
    assert mcp_server.skill_note("0123456789ab", "claude-ai", desktop) == ""  # once a session
    assert mcp_server.skill_note(None, "claude-code", code) == ""  # an app with no uploaded skill
    old = Ctx("claude-ai")
    first = mcp_server.first_rules(old)
    assert first.startswith(mcp_server.SKILL_OUTDATED) and "The rules of the answers" in first
    assert "Independent assessment" in first and mcp_server.first_rules(old) == ""  # once a session
    guided = Ctx("claude-code")
    mcp_server.guided(guided)
    again = mcp_server.first_rules(guided)  # the form comes with the first search even after the guide
    assert again.startswith("The rules of the answers") and mcp_server.SKILL_OUTDATED not in again
    assert "Independent assessment" in skill.rules("general") and "Independent assessment" in mcp_server.OLD_SKILL


def test_a_workspace_and_a_folder_of_the_pc_on_another_disk_reach_every_app(home, tmp_path, monkeypatch):
    """A colleague's install with the workspace on D: had to write paths into the settings of the apps by hand: a
    later assistant-x connect in a new shell (no AX_WORKSPACE) took Documents\Assistant X. The installation
    remembers its workspace and a moved folder of the PC (machine_dir.txt), and connect writes both into every app."""
    from assistant_x.core import workspace

    monkeypatch.delenv("AX_MACHINE_DIR", raising=False)
    monkeypatch.setenv("USERPROFILE", str(home))
    disk_d = tmp_path / "D"
    ws = disk_d / "Library"
    ws.mkdir(parents=True)
    (ws / workspace.CONFIG).write_text('profile = "general"\n', encoding="utf-8")
    moved = workspace.move_machine_dir(disk_d / "AssistantX")
    monkeypatch.delenv("AX_MACHINE_DIR")  # a new shell: only machine_dir.txt tells
    assert workspace.machine_dir() == moved and (workspace.default_machine_dir() / workspace.MOVED).is_file()
    workspace.remember(ws)
    monkeypatch.delenv("AX_WORKSPACE")
    monkeypatch.chdir(tmp_path)
    assert workspace.find() == ws.resolve()
    e = entry("reader", True)
    assert e["env"]["AX_WORKSPACE"] == str(ws.resolve()) and e["env"]["AX_MACHINE_DIR"] == str(moved)
    codex.connect(e, False)
    data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["mcp_servers"]["assistant-x"]["env"]["AX_MACHINE_DIR"] == str(moved)
    workspace.move_machine_dir(workspace.default_machine_dir())  # back: the pointer goes, nothing else is told
    monkeypatch.delenv("AX_MACHINE_DIR")
    assert (
        workspace.machine_dir() == workspace.default_machine_dir() and "AX_MACHINE_DIR" not in entry("reader", True)["env"]
    )
    (ws / workspace.CONFIG).unlink()  # a remembered folder that is no workspace any more: the default again
    assert workspace.find() == workspace.default_root()
