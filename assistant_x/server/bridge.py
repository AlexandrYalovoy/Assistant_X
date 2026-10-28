# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The stdio bridge of an app to the library service: what every app (Claude, Codex, DeepSeek Harness, LM Studio)
starts as its MCP server.

    assistant-x mcp [--tools reader|all] [--compact]

It imports nothing heavy and answers the handshake (initialize) at once, from itself while the service is starting;
it starts the service of the workspace when it is not running (server/service.py, hidden, no console window), reads
the token of the machine folder itself (no secret in the settings of an app) and passes every message both ways:
a JSON line of stdin is POSTed to http://127.0.0.1:<port>/mcp, the JSON or the events of the answer are written to
stdout as lines. A service that is gone (closed after its idle time, killed) is started again and the message sent
once more. --tools reader passes only the reading tools (server/toolsets.py), --compact cuts the answers for small
local models."""

import argparse, http.client, json, os, sys, threading, time

from assistant_x.core import lock, proc
from assistant_x.server import service, texts, toolsets

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")  # answered by the bridge itself at the start
DEFAULT_PROTOCOL = "2025-06-18"
START_TIMEOUT = 180  # s: a cold start imports the server and the search libraries
QUICK = 0.8  # s: how long initialize waits for a running service before the bridge answers it itself
CALL_TIMEOUT = 900  # s: one request (a base recalculation answers at once, a search in seconds)


class Gone(Exception):
    """The service does not answer (no process, refused, reset): start it again."""


class NoAnswer(Exception):
    """A request reached the service but no answer came in time (or the answer broke off after a part of it reached
    the client): it may be running there, so it is not sent again."""


class Bridge:
    def __init__(self, toolset="all", compact=False, out=None, root=None):
        self.toolset, self.compact = toolset, compact
        self.out = out or sys.stdout.buffer
        self.root = root
        self.session = None  # Mcp-Session-Id of the service
        self.protocol = None
        self.init_params = None  # the initialize of the client, sent again to a new service
        self.upstream = False  # the service has had our initialize
        self._out_lock = threading.Lock()
        self._up_lock = threading.Lock()
        self.calls = {}  # id -> tool name of a tools/call in work (for --tools and --compact on its answer)
        self.lists = set()  # ids of tools/list requests in work
        self.trace = None  # AX_LOG_LEVEL=DEBUG: bridge-<id>.log beside the service log, a line per message
        if service.log_level() == "DEBUG":
            self.trace = service.files(root)["log"].replace("service-", "bridge-")

    def note(self, msg, seconds, outcome):
        if not self.trace:
            return
        what = msg.get("method") or "response"
        name = ((msg.get("params") or {}).get("name") or "") if what == "tools/call" else ""
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tpid {os.getpid()}\t{what} {name}\tid {msg.get('id')}\t{seconds:.3f} s\t{outcome}\n"
        try:
            with open(self.trace, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    # ---------- output ----------

    def write(self, msg):
        data = (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._out_lock:
            self.out.write(data)
            self.out.flush()

    def error(self, rid, code, message):
        self.write({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})

    # ---------- the service ----------

    def info(self):
        return service.read_info(self.root)

    def token(self):
        from assistant_x.core import workspace

        try:
            with open(os.path.join(str(workspace.machine_dir()), "mcp_http_token.txt"), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def healthy(self, info, timeout=2.0):
        if not info:
            return False
        try:
            c = http.client.HTTPConnection("127.0.0.1", int(info["port"]), timeout=timeout)
            c.request("GET", "/health", headers={"Authorization": f"Bearer {self.token()}"})
            r = c.getresponse()
            ok = r.status == 200 and json.loads(r.read() or b"{}").get("pid") == info.get("pid")
            c.close()
            return ok
        except (OSError, ValueError, http.client.HTTPException):
            return False

    def start(self):
        """Start the service of the workspace unless another bridge does it now; wait until it answers."""
        paths = service.files(self.root)
        os.makedirs(os.path.dirname(paths["start"]), exist_ok=True)
        deadline = time.monotonic() + START_TIMEOUT
        spawned, held = False, None
        try:
            while time.monotonic() < deadline:
                info = self.info()
                if self.healthy(info):
                    return info
                if not spawned:
                    held = held or lock.exclusive(paths["start"])  # one bridge starts it, the others wait
                    if held is not None:
                        probe = lock.exclusive(paths["lock"])  # held: a service runs and is still loading
                        if probe is not None:
                            probe.close()
                            self.spawn(paths["log"])
                        spawned = True
                time.sleep(0.3)
        finally:
            if held is not None:
                held.close()
        raise Gone(f"the library service did not start in {START_TIMEOUT} s (its log: {paths['log']})")

    def spawn(self, log):
        """The service, detached and hidden (core/proc.py): it outlives the bridge and the app. While the bridge lives
        it waits for it, so a service that ends is no zombie of the bridge (Linux)."""
        with open(log, "ab") as f:
            p = proc.popen(
                [proc.python(), "-m", "assistant_x.server.service"],
                env=proc.python_env(dict(os.environ, PYTHONUTF8="1")),
                stdin=proc.DEVNULL,
                stdout=f,
                stderr=f,
                detach=True,
            )
        threading.Thread(target=p.wait, daemon=True).start()

    # ---------- HTTP ----------

    def post(self, msg, info=None, sink=None):
        """POST one message; the messages of the answer (none for a notification or a response). With sink every
        message of an event stream goes to it as it comes (a request of the service inside a call, such as a question
        to the user, reaches the client while the call is open) and none is returned."""
        info = info or self.info()
        if not info:
            raise Gone("no service")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token()}",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        try:
            c = http.client.HTTPConnection("127.0.0.1", int(info["port"]), timeout=CALL_TIMEOUT)
            c.request("POST", "/mcp", body=json.dumps(msg).encode("utf-8"), headers=headers)
        except (OSError, http.client.HTTPException) as e:
            c.close()
            raise Gone(str(e)) from e
        passed = 0  # messages of the answer already given to the sink
        try:
            r = c.getresponse()
            sid = r.getheader("Mcp-Session-Id")
            if sid:
                self.session = sid
            if r.status == 404 and self.session:
                raise Gone("session not found")  # a new service: initialize again
            if r.status in (202, 204):
                r.read()
                return []
            kind = (r.getheader("Content-Type") or "").split(";")[0].strip()
            if r.status >= 400:
                body = r.read().decode("utf-8", "replace")
                try:
                    return [json.loads(body)]
                except ValueError:
                    rid = msg.get("id") if isinstance(msg, dict) else None
                    return [{"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": f"{r.status}: {body[:300]}"}}]
            if kind == "text/event-stream":
                if sink is None:
                    return list(self.events(r))
                for m in self.events(r):
                    passed += 1
                    sink(m)
                return []
            body = r.read()
            return [json.loads(body)] if body.strip() else []
        except TimeoutError as e:
            raise NoAnswer(f"the library service did not answer in {CALL_TIMEOUT} s") from e
        except (OSError, http.client.HTTPException) as e:
            if passed:
                raise NoAnswer(f"the answer of the library service broke off: {e}") from e
            raise Gone(str(e)) from e
        finally:
            c.close()

    @staticmethod
    def events(r):
        """The JSON messages of a server-sent event stream."""
        data = []
        for raw in iter(r.readline, b""):
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                if data:
                    text = "\n".join(data)
                    data = []
                    try:
                        yield json.loads(text)
                    except ValueError:
                        pass
                continue
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        if data:
            try:
                yield json.loads("\n".join(data))
            except ValueError:
                pass

    def ensure(self, fresh=False):
        """The service runs and has had our initialize (again after a new start)."""
        with self._up_lock:
            if self.upstream and not fresh:
                return
            info = self.info()
            if fresh or not self.healthy(info):
                info = self.start()
            self.session = None
            params = dict(
                self.init_params or {"capabilities": {}, "clientInfo": {"name": "assistant-x bridge", "version": "0"}}
            )
            params["protocolVersion"] = self.protocol or params.get("protocolVersion") or DEFAULT_PROTOCOL
            got = self.post({"jsonrpc": "2.0", "id": "ax-bridge-init", "method": "initialize", "params": params}, info)
            result = next((m.get("result") for m in got if m.get("id") == "ax-bridge-init"), None)
            if not result:
                raise Gone(f"the service refused initialize: {got}")
            self.protocol = result.get("protocolVersion") or self.protocol
            self.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, info)
            self.upstream = True

    def forward(self, msg):
        """Send msg to the service (a new start and one more try when it is gone before it got the message) and write
        the answers as they come. A message the service got but did not answer in time is not sent again."""
        for attempt in (0, 1):
            try:
                self.ensure(fresh=attempt == 1)
                for m in self.post(msg, sink=lambda m: self.write(self.adjust(m))):
                    self.write(self.adjust(m))
                return
            except NoAnswer as e:
                self.calls.pop(msg.get("id"), None)
                if "id" in msg and "method" in msg:
                    self.error(msg["id"], -32603, str(e))
                return
            except Gone as e:
                self.upstream = False
                if attempt:
                    if "id" in msg and "method" in msg:
                        self.error(msg["id"], -32603, f"The library service is not available: {e}")
                    return

    # ---------- tool sets and the compact mode ----------

    def adjust(self, m):
        rid = m.get("id")
        result = m.get("result")
        if rid in self.lists and isinstance(result, dict) and isinstance(result.get("tools"), list):
            self.lists.discard(rid)
            tools = [t for t in result["tools"] if toolsets.allowed(t.get("name"), self.toolset)]
            m = dict(m, result=dict(result, tools=toolsets.compact_tools(tools) if self.compact else tools))
        elif rid in self.calls and isinstance(result, dict):
            self.calls.pop(rid, None)
            if self.compact and isinstance(result.get("content"), list):
                m = dict(m, result=dict(result, content=toolsets.compact_content(result["content"])))
        return m

    # ---------- the messages of the client ----------

    def initialize(self, msg):
        params = msg.get("params") or {}
        asked = params.get("protocolVersion")
        self.protocol = asked if asked in PROTOCOLS else DEFAULT_PROTOCOL
        self.init_params = dict(params, protocolVersion=self.protocol)
        info = self.info()
        if self.healthy(info, timeout=QUICK):  # a running service answers itself (its own instructions and version)
            try:
                self.upstream = False
                self.session = None
                got = self.post(dict(msg, params=self.init_params), info)
                result = next((m.get("result") for m in got if m.get("id") == msg.get("id")), None)
                if result:
                    self.protocol = result.get("protocolVersion") or self.protocol
                    self.upstream = "pending"  # the client's notifications/initialized completes it
                    self.write({"jsonrpc": "2.0", "id": msg.get("id"), "result": result})
                    return
            except (Gone, NoAnswer):
                pass
        from assistant_x import __version__

        self.write(
            {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "protocolVersion": self.protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "Assistant X", "version": __version__},
                    "instructions": texts.INSTRUCTIONS,
                },
            }
        )
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self):
        try:
            self.ensure()
        except (Gone, NoAnswer):
            pass  # the first request tries again and reports it

    def handle(self, msg):
        method = msg.get("method")
        if method == "initialize":
            return self.initialize(msg)
        if method == "notifications/initialized":
            if self.upstream == "pending":
                try:
                    self.post(msg)
                    self.upstream = True
                except (Gone, NoAnswer):
                    self.upstream = False
            return
        if method == "ping" and "id" in msg:
            return self.write({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
        if method == "tools/list":
            self.lists.add(msg.get("id"))
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if not toolsets.allowed(name, self.toolset):
                return self.error(msg.get("id"), -32602, f"Unknown tool: {name}")
            self.calls[msg.get("id")] = name
            if self.compact:
                msg = dict(msg, params=dict(params, arguments=toolsets.compact_arguments(name, params.get("arguments"))))
        if method and method.startswith("notifications/") and self.upstream is not True:
            return  # nothing to tell a service that has not started yet
        self.forward(msg)

    def run(self, stdin=None):
        stdin = stdin or sys.stdin.buffer
        workers = []
        for raw in iter(stdin.readline, b""):
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.error(None, -32700, "Parse error")
                continue
            if not isinstance(msg, dict):
                self.error(None, -32600, "Batches are not supported")
                continue
            if msg.get("method") == "initialize":
                self.handle(msg)  # in order: the requests after it see its state
                continue
            t = threading.Thread(target=self._safe, args=(msg,), daemon=True)
            t.start()
            workers.append(t)
            workers = [w for w in workers if w.is_alive()]
        for t in workers:  # stdin closed: let the answers in work reach the client
            t.join(timeout=CALL_TIMEOUT)

    def _safe(self, msg):
        t = time.monotonic()
        try:
            self.handle(msg)
            self.note(msg, time.monotonic() - t, "ok")
        except Exception as e:  # noqa: BLE001 — one message failed: the client gets an error, the bridge goes on
            self.note(msg, time.monotonic() - t, f"error: {e}")
            if "id" in msg and "method" in msg:
                self.error(msg["id"], -32603, f"Bridge error: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x mcp", description="The stdio bridge of an app to the library service")
    ap.add_argument("--tools", default="all", help="reader: only the reading tools; all (default): every tool")
    ap.add_argument("--compact", action="store_true", help="short descriptions and answers for small local models")
    a = ap.parse_args(argv)
    from assistant_x.core import workspace

    workspace.take_over()  # an app connected before 0.5.1 starts the bridge first
    Bridge(toolsets.check(a.tools), a.compact).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
