# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bridge passes the events of a tool call to the client as they come: a request of the service inside a call
(MCP elicitation: the user is asked for a yes) reaches the client while the call is open, and the client's answer
reaches the service. A call that timed out after it was sent is not sent again."""

import io, json, queue, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assistant_x.server import bridge


class FakeService:
    """A service on 127.0.0.1: initialize, and a tools/call that asks the client a question before it answers."""

    def __init__(self, hang=False):
        self.answered = threading.Event()
        self.calls = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self._json({"pid": 4242})

            def do_POST(self):
                msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if msg.get("method") == "initialize":
                    return self._json({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18"}})
                if "method" not in msg:  # the client's answer to the question
                    fake.answer = msg
                    fake.answered.set()
                    self.send_response(202)
                    self.end_headers()
                    return
                if msg.get("method") != "tools/call":
                    self.send_response(202)
                    self.end_headers()
                    return
                fake.calls.append(msg)
                if hang:
                    time.sleep(3)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                ask = {"jsonrpc": "2.0", "id": 7, "method": "elicitation/create", "params": {"message": "Remove?"}}
                self.wfile.write(f"data: {json.dumps(ask)}\n\n".encode())
                self.wfile.flush()
                ok = fake.answered.wait(10)
                done = {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": f"asked {ok}"}]}}
                self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
                self.wfile.flush()

            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.info = {"port": self.http.server_address[1], "pid": 4242}

    def close(self):
        self.http.shutdown()


class Out(io.RawIOBase):
    def __init__(self):
        self.q = queue.Queue()

    def write(self, data):
        self.q.put(json.loads(data))
        return len(data)

    def flush(self):
        pass


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path))
    (tmp_path / "mcp_http_token.txt").write_text("t", encoding="utf-8")


def make(fake):
    out = Out()
    b = bridge.Bridge(out=out, root="no such workspace")
    b.info = lambda: fake.info
    b.start = lambda: (_ for _ in ()).throw(AssertionError("no new service may be started"))
    return b, out


def test_a_question_inside_a_call_reaches_the_client_and_its_answer_the_service(machine):
    fake = FakeService()
    b, out = make(fake)
    try:
        t = threading.Thread(
            target=b.handle,
            args=({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "base_remove", "arguments": {}}},),
            daemon=True,
        )
        t.start()
        ask = out.q.get(timeout=5)  # before the call ends
        assert ask["method"] == "elicitation/create" and ask["id"] == 7
        b.handle({"jsonrpc": "2.0", "id": 7, "result": {"action": "accept", "content": {"confirm": True}}})
        done = out.q.get(timeout=10)
        assert done["id"] == 1 and done["result"]["content"][0]["text"] == "asked True"
        assert fake.answer["result"]["action"] == "accept" and len(fake.calls) == 1
    finally:
        fake.close()


def test_a_call_that_timed_out_is_not_sent_again(machine, monkeypatch):
    fake = FakeService(hang=True)
    monkeypatch.setattr(bridge, "CALL_TIMEOUT", 1)
    b, out = make(fake)
    try:
        b.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "intake_run", "arguments": {}}})
        err = out.q.get(timeout=5)
        assert err["id"] == 1 and "error" in err and "did not answer" in err["error"]["message"]
        assert len(fake.calls) == 1  # once: it may be running in the service
    finally:
        fake.close()
