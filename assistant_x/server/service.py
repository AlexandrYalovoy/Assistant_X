# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The library service: one MCP server of a workspace for every app of the PC (Claude, Codex, DeepSeek Harness,
LM Studio), streamable HTTP on 127.0.0.1. The models load once (on the video card when there is one) and every app
connects through its stdio bridge (assistant-x mcp, server/bridge.py), which starts the service when it is not running.

    assistant-x service [--port N] [--idle MINUTES]

- One service per workspace: service-<id>.lock in the machine folder (%LOCALAPPDATA%\AssistantX) is held while it
  runs, service-<id>.json says its pid, port and version (a second start exits at once).
- The port: N (default 8765, AX_SERVICE_PORT), a free one when it is taken.
- Every request needs the bearer token of mcp_http_token.txt in the machine folder; only the Host and Origin of
  127.0.0.1 and localhost are taken (DNS rebinding). GET /health (with the token) answers {"version", "pid"}.
- It exits after --idle minutes without a request (default 30): the video memory is free again for a local model.
- The bridge starts it hidden (core/proc.py, no console window); its log is service-<id>.log beside the lock."""

import argparse, hashlib, json, os, socket, sys, threading, time

from assistant_x.core import lock, workspace

PORT = 8765
IDLE_MINUTES = 30


def key(root=None):
    """The id of a workspace in the names of its service files: 10 hex characters of its folder (case-folded)."""
    root = str(root or workspace.find())
    return hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:10]


def files(root=None):
    """{lock, info, log, start} paths of the service of a workspace."""
    d, k = workspace.machine_dir(), key(root)
    return {
        "lock": str(d / f"service-{k}.lock"),
        "info": str(d / f"service-{k}.json"),
        "log": str(d / f"service-{k}.log"),
        "start": str(d / f"service-{k}.start.lock"),
    }


def read_info(root=None):
    """The service-<id>.json of a workspace, or None."""
    try:
        with open(files(root)["info"], encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) and info.get("port") else None
    except (OSError, ValueError):
        return None


def bind(port):
    """A listening socket on 127.0.0.1:port, or on a free port when that one is taken."""
    for p in (port, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":  # no second listener on the same port (SO_EXCLUSIVEADDRUSE)
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        try:
            s.bind(("127.0.0.1", p))
        except OSError:
            s.close()
            continue
        s.listen(64)
        return s
    raise SystemExit("no free port on 127.0.0.1")


class Activity:
    """The ASGI app with the time of the last request and the number of requests in work; GET /health answered here."""

    def __init__(self, app, health):
        self.app, self.health = app, health
        self.active, self.last = 0, time.monotonic()
        self._lock = threading.Lock()

    def idle(self):
        """Seconds since the last request ended, 0 while one is in work."""
        with self._lock:
            return 0.0 if self.active else time.monotonic() - self.last

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") == "/health":
            body = json.dumps(self.health).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        with self._lock:
            self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            with self._lock:
                self.active -= 1
                self.last = time.monotonic()


def write_info(path, info):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(info, f)
    os.replace(tmp, path)


def drop_info(path):
    """Remove service-<id>.json when it is still of this process."""
    try:
        with open(path, encoding="utf-8") as f:
            mine = json.load(f).get("pid") == os.getpid()
        if mine:
            os.remove(path)
    except (OSError, ValueError, AttributeError):
        pass


def main(argv=None):
    from assistant_x import __version__
    from assistant_x.core import env

    ap = argparse.ArgumentParser(prog="assistant-x service", description="The library service of the workspace")
    ap.add_argument("--port", type=int, default=int(env.get("SERVICE_PORT") or PORT))
    ap.add_argument("--idle", type=float, default=float(env.get("SERVICE_IDLE") or IDLE_MINUTES), help="minutes")
    a = ap.parse_args(argv)
    paths = files()
    os.makedirs(os.path.dirname(paths["lock"]), exist_ok=True)
    held = lock.exclusive(paths["lock"])
    if held is None:
        print(f"the library service of this workspace runs already ({paths['info']})", file=sys.stderr)
        return 0
    sock = bind(a.port)
    port = sock.getsockname()[1]

    import uvicorn
    from assistant_x.core import debuglog
    from assistant_x.server import mcp_server as S

    token, token_path = S.http_token()
    health = {"version": __version__, "pid": os.getpid(), "workspace": str(workspace.find())}
    app = Activity(S.mcp_app(port), health)
    first = S.take_models_lock()
    debuglog.log_call("service start", 0, True, {"pid": os.getpid(), "port": port, "models": first})
    if first:
        threading.Thread(target=S._warm_up, daemon=True).start()
    server = uvicorn.Server(uvicorn.Config(S.bearer(app, token), log_level="warning", lifespan="on"))

    def watch():
        while not server.should_exit:
            time.sleep(min(30.0, a.idle * 60 / 4 or 1))
            if app.idle() >= a.idle * 60:
                print(f"library service: {a.idle:g} min without a request, exiting", file=sys.stderr)
                server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    write_info(paths["info"], {**health, "port": port, "started": time.time(), "token_file": token_path})
    print(f"library service: http://127.0.0.1:{port}/mcp (pid {os.getpid()})", file=sys.stderr)
    try:
        server.run(sockets=[sock])
    except Exception as e:  # noqa: BLE001 — logged for the debug report, then the bridge starts a new one
        debuglog.log_error("service run", e)
        raise
    finally:
        drop_info(paths["info"])
        held.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
