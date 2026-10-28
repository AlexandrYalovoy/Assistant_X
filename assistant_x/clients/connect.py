# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connect the apps of this PC to the library.

    assistant-x connect APP|auto [--full | --reader] [--compact] [--dry-run]   write the entry (and the skill)
    assistant-x connect --list                                                  the apps, found and connected
    assistant-x connect --check [APP]                                           the handshake and a search, per app
    assistant-x disconnect APP|all [--dry-run]                                  take the entry out

APP: claude_desktop, claude_code, codex, dsh, lmstudio; auto: every one found on this PC. The tool set of an app is
its default (the reading tools for DeepSeek Harness and LM Studio, all for Claude and Codex) unless --full (all, no
compact answers) or --reader; LM Studio gets the compact answers by default."""

import argparse, json, os, sys, threading, time

from assistant_x import clients as K
from assistant_x.core import proc


def choose(names):
    if names == ["auto"]:
        return [n for n in K.APPS if K.app(n).found()]
    if names == ["all"]:
        return list(K.APPS)
    return [K.app(n).NAME for n in names]


def connect(names, toolset=None, compact=None, dry=False, python=None, root=None, say=print):
    """Write the entry of every app; {app: [(file, status)]}."""
    from assistant_x.clients import skills

    done = {}
    for name in choose(names):
        a = K.app(name)
        ts = toolset or a.TOOLSET
        e = K.entry(python, ts, a.COMPACT if compact is None else compact, root)
        done[name] = a.connect(e, dry)
        if a.skill_dir() is not None and not dry:
            done[name] += skills.install(name)
        for path, status in done[name]:
            say(f"{a.TITLE}: {path}: {status}")
    if not done:
        say("No app of the list was found on this PC: " + ", ".join(K.APPS))
    return done


def disconnect(names, dry=False, say=print):
    from assistant_x.clients import skills

    done = {}
    for name in choose(names):
        a = K.app(name)
        done[name] = a.disconnect(dry)
        if a.skill_dir() is not None and not dry:
            done[name] += skills.remove(name)
        for path, status in done[name]:
            say(f"{a.TITLE}: {path}: {status}")
    return done


def listing():
    rows = []
    for name in K.APPS:
        a = K.app(name)
        e = a.read()
        tools = "reader" if e and "--tools" in (e.get("args") or []) else "all" if e else ""
        bridge = bool(e) and "assistant_x.server.bridge" in (e.get("args") or [])
        rows.append(
            {
                "app": name,
                "title": a.TITLE,
                "found": a.found(),
                "connected": bool(e),
                "through_service": bridge,
                "tools": tools,
                "compact": bool(e) and "--compact" in (e.get("args") or []),
                "config": a.configs()[0],
            }
        )
    return rows


def probe(e, query="pressure", timeout=240):
    """Start the server of an entry as its app does, make the handshake, list the tools and search once:
    {ok, initialize_s, tools, search_s, answer | error}."""
    t0 = time.monotonic()
    p = proc.popen(
        [e["command"], *e["args"]],
        stdin=proc.PIPE,
        stdout=proc.PIPE,
        stderr=proc.DEVNULL,
        env=dict(os.environ, **(e.get("env") or {})),
        hidden=True,
    )
    got, lock = {}, threading.Condition()

    def reader():
        for raw in iter(p.stdout.readline, b""):
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            with lock:
                got[m.get("id")] = m
                lock.notify_all()

    threading.Thread(target=reader, daemon=True).start()

    def ask(rid, method, params):
        p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n").encode())
        p.stdin.flush()
        with lock:
            if not lock.wait_for(lambda: rid in got, timeout):
                raise TimeoutError(f"no answer to {method} in {timeout} s")
            m = got[rid]
        if "error" in m:
            raise RuntimeError(m["error"].get("message"))
        return m["result"]

    out = {"ok": False}
    try:
        init = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "assistant-x check", "version": "1"},
        }
        ask(1, "initialize", init)
        out["initialize_s"] = round(time.monotonic() - t0, 2)
        p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        p.stdin.flush()
        out["tools"] = len(ask(2, "tools/list", {})["tools"])
        t1 = time.monotonic()
        r = ask(3, "tools/call", {"name": "search_library", "arguments": {"query": query, "k": 1}})
        out["search_s"] = round(time.monotonic() - t1, 2)
        out["answer"] = " ".join(c.get("text", "") for c in r.get("content", []))[:200]
        out["ok"] = not r.get("isError")
    except (OSError, TimeoutError, RuntimeError) as err:
        out["error"] = str(err)
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=10)
        except (OSError, proc.TimeoutExpired):
            p.kill()
    return out


def check(names, say=print):
    res = {}
    for name in choose(names or ["all"]):
        a = K.app(name)
        e = a.read()
        if not e:
            if names:
                say(f"{a.TITLE}: not connected")
            continue
        res[name] = r = probe(e)
        if r["ok"]:
            say(f"{a.TITLE}: in order — handshake {r['initialize_s']} s, {r['tools']} tools, a search in {r['search_s']} s")
        else:
            say(f"{a.TITLE}: FAILED — {r.get('error') or r.get('answer')}")
    if not res:
        say("No app is connected: assistant-x connect auto")
    return res


def main(argv=None, disconnecting=False):
    prog = "assistant-x disconnect" if disconnecting else "assistant-x connect"
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    ap.add_argument("apps", nargs="*", help=f"{', '.join(K.APPS)}, auto or all")
    ap.add_argument("--dry-run", action="store_true")
    if not disconnecting:
        ap.add_argument("--full", action="store_true", help="every tool, no compact answers")
        ap.add_argument("--reader", action="store_true", help="only the reading tools")
        ap.add_argument("--compact", action="store_true", help="short descriptions and answers (small local models)")
        ap.add_argument("--list", action="store_true", help="the apps: found, connected")
        ap.add_argument("--check", action="store_true", help="the handshake and a search through every entry")
        ap.add_argument("--json", action="store_true", help="the result as JSON")
    a = ap.parse_args(argv)
    if disconnecting:
        if not a.apps:
            ap.error("name the app (or all)")
        disconnect(a.apps, a.dry_run)
        return 0
    if a.list:
        rows = listing()
        if a.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            for r in rows:
                state = "connected" + (f" ({r['tools']}{', compact' if r['compact'] else ''})" if r["tools"] else "")
                state = state if r["connected"] else "found, not connected" if r["found"] else "not found"
                print(f"{r['app']:<15} {r['title']:<36} {state:<28} {r['config']}")
        return 0
    if a.check:
        res = check(a.apps)
        if a.json:
            print(json.dumps(res, ensure_ascii=False))
        return 0 if res and all(r["ok"] for r in res.values()) else 1
    if not a.apps:
        ap.error("name the app (or auto)")
    toolset = "all" if a.full else "reader" if a.reader else None
    compact = False if a.full else True if a.compact else None
    done = connect(a.apps, toolset, compact, a.dry_run, say=(lambda s: None) if a.json else print)
    if a.json:
        print(json.dumps({k: [list(x) for x in v] for k, v in done.items()}, ensure_ascii=False))
    refused = [s for v in done.values() for _, s in v if s.startswith(("left alone", "refused"))]
    return 1 if refused or not done else 0


def disconnect_main(argv=None):
    return main(argv, disconnecting=True)


if __name__ == "__main__":
    sys.exit(main())
