# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The library service and its stdio bridges, as the apps run them: three bridges at once start one service (one
process with the models), the handshake is answered in less than a second, a killed service comes back on the next
call, an idle one exits by itself."""

import json, os, queue, sys, threading, time

import psutil
import pytest

from assistant_x.core import proc
from assistant_x.server import bridge, service


class App:
    """A bridge started as an app starts it: JSON lines on its stdin and stdout."""

    def __init__(self, *args):
        self.p = proc.popen(
            [sys.executable, "-m", "assistant_x.server.bridge", *args],
            stdin=proc.PIPE,
            stdout=proc.PIPE,
            stderr=proc.DEVNULL,
            env=dict(os.environ, PYTHONUTF8="1"),
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.n = 0

    def _read(self):
        for raw in iter(self.p.stdout.readline, b""):
            self.lines.put(json.loads(raw))

    def send(self, msg):
        self.p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def ask(self, method, params=None, timeout=240):
        self.n += 1
        rid = self.n
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                m = self.lines.get(timeout=1)
            except queue.Empty:
                continue
            if m.get("id") == rid:
                return m
        raise AssertionError(f"no answer to {method} in {timeout} s")

    def hello(self):
        t = time.monotonic()
        init = self.ask(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        )
        took = time.monotonic() - t
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return init, took

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:  # noqa: BLE001
            self.p.kill()


@pytest.fixture
def place(mini, tmp_path, monkeypatch):
    """The mini library as the workspace of the service, a machine folder of its own; the service killed after."""
    monkeypatch.setenv("AX_WORKSPACE", mini["root"])
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.setenv("AX_MCP_LOCK_FILE", str(tmp_path / "mcp_server.lock"))
    monkeypatch.setenv("AX_SERVICE_PORT", "0")
    apps = []
    yield apps
    for a in apps:
        a.close()
    info = service.read_info(mini["root"])
    if info:
        try:
            psutil.Process(info["pid"]).kill()
        except psutil.Error:
            pass


def gone(pid, timeout=30):
    """Wait until the process is gone (or a zombie: its parent has not reaped it yet)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(0.2)
    raise AssertionError(f"process {pid} still runs")


def services(since):
    out = []
    for p in psutil.process_iter(["cmdline", "create_time"]):
        try:
            if "assistant_x.server.service" in " ".join(p.info["cmdline"] or []) and p.info["create_time"] >= since - 1:
                out.append(p.pid)
        except psutil.Error:
            pass
    return out


def test_three_apps_one_service_and_a_killed_one_comes_back(place, mini):
    since = time.time()
    apps = [App(), App("--tools", "reader"), App("--tools", "reader", "--compact")]
    place.extend(apps)
    for a in apps:
        init, took = a.hello()
        assert took < 1.0, f"initialize took {took:.2f} s"
        r = init["result"]
        assert r["serverInfo"]["name"] == "Assistant X" and "library_guide" in r["instructions"]
    names = [{t["name"] for t in a.ask("tools/list")["result"]["tools"]} for a in apps]
    assert len(names[0]) >= 23 and names[1] == names[2] == set(bridge.toolsets.READER)
    found = [a.ask("tools/call", {"name": "search_library", "arguments": {"query": "обводнённости"}}) for a in apps]
    for f in found:
        assert "[N-00001, PDF" in f["result"]["content"][0]["text"], f
    assert len(services(since)) == 1  # one process with the models for the three apps
    info = service.read_info(mini["root"])
    assert info and info["pid"] == services(since)[0]
    refused = apps[1].ask("tools/call", {"name": "intake_run", "arguments": {}})
    assert refused["error"]["message"] == "Unknown tool: intake_run"  # not in the reader set

    psutil.Process(info["pid"]).kill()  # gone: the next call starts it again
    gone(info["pid"])
    again = apps[0].ask(
        "tools/call", {"name": "read_pages", "arguments": {"code": "N-00001", "start_page": 1, "end_page": 1}}
    )
    assert "result" in again and not again["result"].get("isError"), again
    new = service.read_info(mini["root"])
    assert new and new["pid"] != info["pid"] and len(services(since)) == 1


def test_an_idle_service_exits(place, mini, monkeypatch):
    monkeypatch.setenv("AX_SERVICE_IDLE", "0.05")  # 3 s
    a = App()
    place.append(a)
    a.hello()
    assert a.ask("tools/call", {"name": "library_guide", "arguments": {}})["result"]["content"][0]["text"]
    pid = service.read_info(mini["root"])["pid"]
    gone(pid, timeout=60)
    assert service.read_info(mini["root"]) is None


def test_a_debug_run_logs_every_message(place, mini, monkeypatch):
    """AX_LOG_LEVEL=DEBUG: the bridge writes a line per message beside the service log, the service logs its
    libraries at DEBUG; unset or unknown is WARNING."""
    monkeypatch.setenv("AX_LOG_LEVEL", "nonsense")
    assert service.log_level() == "WARNING"
    monkeypatch.setenv("AX_LOG_LEVEL", "debug")
    assert service.log_level() == "DEBUG"
    a = App("--tools", "reader")
    place.append(a)
    a.hello()
    assert "result" in a.ask("tools/call", {"name": "search_library", "arguments": {"query": "обводнённости"}})
    trace = service.files(mini["root"])["log"].replace("service-", "bridge-")
    end = time.monotonic() + 10
    while time.monotonic() < end and not (
        os.path.exists(trace) and "search_library" in open(trace, encoding="utf-8").read()
    ):
        time.sleep(0.2)
    lines = open(trace, encoding="utf-8").read().splitlines()
    assert any("tools/call search_library" in x and x.endswith("ok") for x in lines), lines


def test_the_bridge_answers_with_its_own_handshake_first():
    """Before the service runs, initialize is answered by the bridge: a known protocol is kept, an unknown one gets
    the default."""
    out = []

    class Out:
        def write(self, data):
            out.append(json.loads(data))

        def flush(self):
            pass

    b = bridge.Bridge(out=Out(), root="no such workspace")
    b.info = lambda: None
    b._warm = lambda: None
    b.initialize({"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    b.initialize({"id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert (
        out[0]["result"]["protocolVersion"] == "2025-03-26"
        and out[1]["result"]["protocolVersion"] == bridge.DEFAULT_PROTOCOL
    )
    assert "library_guide" in out[0]["result"]["instructions"]


def test_the_service_files_are_per_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path))
    a, b = service.files(tmp_path / "one"), service.files(tmp_path / "two")
    assert a["info"] != b["info"] and os.path.dirname(a["lock"]) == str(tmp_path)
    assert service.key(tmp_path / "One") == service.key(tmp_path / "one") or os.name != "nt"
