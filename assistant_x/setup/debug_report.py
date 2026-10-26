# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build "debug_report_<PC id>_<date>.md" in debug/: computer, Python environment, installation, base,
Claude Desktop connection, self-test of every search layer and the failure journal.
Every section is collected on its own, so the report is written even when half of the installation is broken.
Usage: assistant-x debug-report [--quick] [--no-open]   (--quick: skip loading the embedding models)"""

import argparse, datetime, glob, hashlib, json, locale, os, platform, shutil, subprocess, sys, time, traceback

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # assistant_x
from assistant_x.core import debuglog

TEST_QUERY = "residence time of oil in a three-phase separator"
PACKAGES = [
    "mcp",
    "numpy",
    "snowballstemmer",
    "pymupdf",
    "sentence-transformers",
    "transformers",
    "torch",
    "huggingface-hub",
    "faiss-cpu",
    "tokenizers",
    "safetensors",
    "anyio",
    "pydantic",
]
ENV_KEYS = [
    "HF_HUB_OFFLINE",
    "HF_HOME",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    "AX_SEARCH_CONFIG",
    "CUDA_VISIBLE_DEVICES",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CONDA_DEFAULT_ENV",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
]
hints = []  # automatic findings, shown at the top of the report


def section(title):
    """Decorator: a section that fails shows its traceback instead of breaking the whole report."""

    def deco(fn):
        def run(*args):
            t = time.time()
            try:
                body = fn(*args)
            except Exception:
                body = "Section not collected, error:\n```\n" + traceback.format_exc() + "```"
            return f"## {title}\n\n{body}\n\n_(collected in {time.time() - t:.1f} s)_\n"

        return run

    return deco


def table(rows, head=("Parameter", "Value")):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |")
    return "\n".join(out)


def sh(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return (p.stdout or p.stderr).strip()
    except Exception as e:
        return f"failed: {type(e).__name__}: {e}"


def size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def cfg_or_none():
    try:
        from assistant_x.core.common import load_config

        return load_config()
    except Exception:
        return None


# ---------------------------------------------------------------- computer
def ram():
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return f"{size(m.ullTotalPhys)}, free {size(m.ullAvailPhys)}"
    if os.path.exists("/proc/meminfo"):
        info = dict(l.split(":", 1) for l in open("/proc/meminfo"))
        return f"{info['MemTotal'].strip()}, available {info['MemAvailable'].strip()}"
    return "unknown"


def cpu_name():
    if os.name == "nt":
        try:
            import winreg

            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def windows_name():
    if os.name != "nt":
        return "—"
    ver = platform.win32_ver()[1]
    try:  # platform reports Windows 11 as 10; builds from 22000 on are 11
        return f"Windows {'11' if int(ver.split('.')[2]) >= 22000 else '10'} {platform.win32_edition() or ''} (build {ver})"
    except (IndexError, ValueError):
        return ver


@section("Computer")
def computer():
    cfg = cfg_or_none()
    rows = [
        ("PC id (a hash of its name)", debuglog.pc_id()),
        ("User", os.environ.get("USERNAME") or os.environ.get("USER", "")),
        ("OS", platform.platform()),
        ("Windows version", windows_name()),
        ("Processor", f"{cpu_name()}, logical cores {os.cpu_count()}"),
        ("Memory", ram()),
    ]
    seen = set()
    for p in [PACKAGE] + ([cfg["library_root"], cfg["index_dir"]] if cfg else []):
        drive = os.path.splitdrive(os.path.abspath(p))[0] or "/"
        if drive in seen or not os.path.exists(p):
            continue
        seen.add(drive)
        u = shutil.disk_usage(p)
        rows.append((f"Disk {drive}", f"free {size(u.free)} of {size(u.total)}"))
        if u.free < 5 * 2**30:
            hints.append(f"Less than 5 GB free on disk {drive}: the build and the embeddings may fail.")
    smi = sh(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used", "--format=csv,noheader"])
    rows.append(
        ("Video card (nvidia-smi)", smi if smi and "failed" not in smi else "no NVIDIA card found or nvidia-smi unavailable")
    )
    return table(rows)


# ---------------------------------------------------------------- python
@section("Python and packages")
def python_env():
    from importlib import metadata

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    rows = [
        ("Version", sys.version.replace("\n", " ")),
        ("Interpreter", sys.executable),
        ("Virtual environment", f"yes ({sys.prefix})" if in_venv else "no"),
        (
            "Encodings",
            f"files {sys.getfilesystemencoding()}, default {locale.getpreferredencoding(False)}, "
            f"UTF-8 mode {'on' if sys.flags.utf8_mode else 'off'}",
        ),
    ]
    if not in_venv:
        hints.append(
            "The report was not started from the search environment (.venv of the code or %LOCALAPPDATA%\\AssistantX\\venv): "
            "the package versions below may differ from what the server sees. Run Setup.bat."
        )
    if sys.version_info < (3, 11):
        hints.append("Python older than 3.11: the program needs 3.11+.")
    for p in PACKAGES:
        try:
            rows.append((p, metadata.version(p)))
        except metadata.PackageNotFoundError:
            rows.append((p, "**not installed**"))
            if p != "faiss-cpu":
                hints.append(f"Package {p} is not installed: run Setup.bat once more")
    try:
        import sqlite3

        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        c.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, 't', 'row')")
        fts = "present (fts5, fts5vocab)"
    except Exception as e:
        fts = f"**missing**: {e}"
        hints.append("SQLite without FTS5: the search by words will not work.")
    rows.append(("SQLite", f"{sqlite3.sqlite_version}, full-text search {fts}"))
    # in a separate process: a broken torch can kill the interpreter outright, and the report must survive that
    probe = (
        "import torch; c = torch.cuda.is_available(); print(f'yes: {torch.cuda.get_device_name(0)}, CUDA {torch.version.cuda}, '"
        "f'memory {torch.cuda.get_device_properties(0).total_memory / 2**30:.1f} GB' if c else 'no')"
    )
    rows.append(("torch sees a video card", sh([sys.executable, "-c", probe], timeout=120)[-300:]))
    rows += [(f"env {k}", os.environ[k]) for k in ENV_KEYS if k in os.environ]
    return table(rows)


# ---------------------------------------------------------------- installation
def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:12]


@section("Search installation")
def installation():
    rows = []
    for p in sorted(
        glob.glob(os.path.join(PACKAGE, "**", "*.py"), recursive=True)
        + glob.glob(os.path.join(PACKAGE, "**", "*.txt"), recursive=True)
    ):
        st = os.stat(p)
        rows.append(
            (
                os.path.relpath(p, PACKAGE),
                size(st.st_size),
                datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                sha(p),
            )
        )
    out = f"Folder: `{PACKAGE}`\n\n" + table(rows, ("File", "Size", "Changed", "SHA-256 (start)"))
    from assistant_x.core import config, env

    cpath = env.get("SEARCH_CONFIG") or str(config.config_path())
    text = open(cpath, encoding="utf-8").read().strip() if os.path.isfile(cpath) else "(no file: the defaults)"
    out += f"\n\nSettings (`{cpath}`):\n```\n{text}\n```\n"
    from assistant_x.core.common import load_config

    cfg = load_config()
    rows = []
    for k in (
        "library_root",
        "texts_dir",
        "cards_dir",
        "catalog",
        "synonyms",
        "index_dir",
        "db",
        "embed_model",
        "rerank_model",
    ):
        p = cfg.get(k)
        if not p:
            continue
        ok = os.path.exists(p)
        what = ""
        if ok and os.path.isdir(p):
            files = [f for f in glob.glob(os.path.join(p, "**", "*"), recursive=True) if os.path.isfile(f)]
            what = f"folder, files {len(files)}, {size(sum(os.path.getsize(f) for f in files))}"
        elif ok:
            what = size(os.path.getsize(p))
        elif k in ("embed_model", "rerank_model") and not os.path.isabs(p):
            what = "a HuggingFace model name (no local folder)"
            if os.environ.get("HF_HUB_OFFLINE") == "1":
                hints.append(
                    f"{k} is not a local folder, and HF_HUB_OFFLINE=1: the model will not load without a downloaded cache."
                )
        elif k == "rerank_model" and cfg.get("rerank") is not True:
            # a reranker is optional: "auto" goes without it (search.may_rerank), so it is not a finding
            what = "missing: the reranker is not part of the kit, the search works without it"
        else:
            what = "**missing**"
            if k not in ("vectors",):
                hints.append(f"No path {k}: {p}")
        rows.append((k, f"`{p}`", what))
    return out + "\n" + table(rows, ("Key", "Path", "State"))


@section("Search base")
def base():
    from assistant_x.core import card as C
    from assistant_x.core.common import load_config, connect, has_column, vectors_path, BASE_SCHEMA, CHUNK_VERSION

    cfg = load_config()
    con = connect(cfg["db"], readonly=True)
    one = lambda q: con.execute(q).fetchone()[0]
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    n_docs, n_chunks = one("SELECT count(*) FROM docs"), one("SELECT count(*) FROM chunks")
    parts = one("SELECT count(*) FROM docs WHERE coalesce(parent, '') != ''") if has_column(con, "docs", "parent") else 0
    with_text = one("SELECT count(*) FROM docs WHERE coalesce(text_file, '') != ''")
    no_vec = one("SELECT count(*) FROM chunks WHERE vec_row IS NULL")
    rows = [
        (
            "Base file",
            f"{size(os.path.getsize(cfg['db']))}, changed "
            f"{datetime.datetime.fromtimestamp(os.path.getmtime(cfg['db'])):%Y-%m-%d %H:%M}",
        ),
        ("Documents", f"{n_docs - parts}" + (f" and parts of documents {parts}" if parts else "")),
        ("Fragments", n_chunks),
        ("Without embeddings", no_vec),
        ("Embedding model", meta.get("embed_model", "—")),
        ("Dimension", meta.get("dim", "—")),
        ("Fragment version", meta.get("chunk_version", "1")),
        ("Base schema", meta.get("base_schema", "1")),
        ("Cards (index/cards)", len(C.paths(cfg["cards_dir"]))),
    ]
    if has_column(con, "chunks", "kind"):
        rows.append(
            (
                "Fragments by kind",
                ", ".join(f"{k}: {n}" for k, n in con.execute("SELECT kind, count(*) FROM chunks GROUP BY kind")),
            )
        )
    if meta.get("base_schema", "1") != BASE_SCHEMA:
        hints.append(
            "The base was built by an earlier version (Markdown cards): on the build PC run "
            "assistant-x build --full and assistant-x embed."
        )
    if meta.get("chunk_version", "1") != CHUNK_VERSION:
        hints.append(
            "The base was built by an earlier version (no section headings): on the build PC run "
            "assistant-x build --full and assistant-x embed."
        )
    if has_column(con, "chunks", "heading") and n_chunks:
        with_head = one("SELECT count(*) FROM chunks WHERE heading != ''")
        rows.append(("With a section heading", f"{with_head} ({with_head / n_chunks:.0%})"))
    texts = len(
        [
            p
            for p in glob.glob(os.path.join(cfg["texts_dir"], "*.md")) + glob.glob(os.path.join(cfg["texts_dir"], "*.txt"))
            if not os.path.basename(p).startswith("_")
        ]
    )
    rows.append(("Text files in texts", texts))
    if texts and abs(texts - with_text) > 1:
        hints.append(
            f"The base has {with_text} documents with a text, but there are {texts} text files: run assistant-x build."
        )
    if no_vec:
        hints.append(
            f"{no_vec} fragments without embeddings: run assistant-x embed (until then only the search by words finds them)."
        )
    vpath = vectors_path(cfg, con)
    others = [os.path.basename(p) for p in glob.glob(os.path.join(cfg["index_dir"], "vectors*.f16")) if p != vpath]
    if others:
        rows.append(
            ("Old embeddings files", ", ".join(others) + " (deleted by the next build, once Claude lets go of them)")
        )
    if os.path.exists(vpath) and meta.get("dim"):
        nvec = os.path.getsize(vpath) // (int(meta["dim"]) * 2)
        maxrow = one("SELECT max(vec_row) FROM chunks")
        rows.append((f"Vectors in {os.path.basename(vpath)}", f"{nvec} ({size(os.path.getsize(vpath))})"))
        if maxrow is not None and maxrow >= nvec:
            hints.append(
                "The base has higher embedding numbers than the file has vectors: the base and the embeddings file come from different builds."
            )
        ann = vpath + ".ivfpq.json"
        rows.append(("FAISS index", open(ann).read() if os.path.exists(ann) else "none"))
        if nvec > 200_000 and not os.path.exists(ann):
            try:
                import faiss  # noqa: F401

                hints.append(
                    "More than 200 thousand vectors and no FAISS index: the search by meaning is slow. "
                    "Run ann.py; if it fails, the reason is in debug\\failures.log."
                )
            except ImportError:
                hints.append(
                    "More than 200 thousand vectors and no FAISS index: the search by meaning is slow. "
                    "Install faiss-cpu and run ann.py."
                )
    rows.append(
        ("Sections", ", ".join(f"{s}: {n}" for s, n in con.execute("SELECT section, count(*) FROM docs GROUP BY section")))
    )
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='objects'").fetchone():  # bookmap.py
        o = dict(con.execute("SELECT kind, count(*) FROM objects GROUP BY kind").fetchall())
        rows.append(
            (
                "Book maps",
                f"outline of {one('SELECT count(DISTINCT code) FROM outline')} documents; "
                f"tables {o.get('t', 0)}, figures {o.get('r', 0)}, formulas {o.get('f', 0)}, "
                f"appendices {o.get('a', 0)}",
            )
        )
    return table(rows)


# ---------------------------------------------------------------- Claude Desktop
def desktop_dirs():
    if os.name == "nt":  # the Microsoft Store build keeps its settings inside its package folder
        return [os.path.join(os.environ.get("APPDATA", ""), "Claude")] + glob.glob(
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*", "LocalCache", "Roaming", "Claude")
        )
    home = os.path.expanduser("~")
    return [os.path.join(home, "Library", "Application Support", "Claude"), os.path.join(home, ".config", "Claude")]


def log_dirs():
    if os.name == "nt":
        return [os.path.join(d, "logs") for d in desktop_dirs()]
    return [os.path.expanduser("~/Library/Logs/Claude"), os.path.expanduser("~/.config/Claude/logs")]


def tail(path, n):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.readlines()[-n:]


@section("Claude Desktop connection")
def desktop():
    out = []
    found = False
    for d in desktop_dirs():
        p = os.path.join(d, "claude_desktop_config.json")
        if not os.path.exists(p):
            continue
        found = True
        conf = json.load(open(p, encoding="utf-8"))
        servers = conf.get("mcpServers", {})
        out.append(f"Settings file: `{p}`, changed {datetime.datetime.fromtimestamp(os.path.getmtime(p)):%Y-%m-%d %H:%M}")
        out.append(f"Local servers: {', '.join(servers) or 'none'}")  # names only: other entries may hold keys
        s = servers.get("assistant-x")
        if not s:
            hints.append("The Claude Desktop settings have no assistant-x server.")
            continue
        cmd, args = s.get("command", ""), s.get("args", [])
        env = {k: (v if k in ENV_KEYS else "…hidden…") for k, v in (s.get("env") or {}).items()}
        out.append(
            table(
                [
                    ("command", f"`{cmd}`" + ("" if os.path.exists(cmd) or shutil.which(cmd) else " **not found**")),
                    ("args", "; ".join(f"`{a}`" + ("" if os.path.exists(a) else " **not found**") for a in args)),
                    ("env", json.dumps(env, ensure_ascii=False)),
                ]
            )
        )
        if cmd and not (os.path.exists(cmd) or shutil.which(cmd)):
            hints.append(f"Claude Desktop starts the server with {cmd}, but there is no such file.")
    if not found:
        out.append("No claude_desktop_config.json found (Claude Desktop is not installed or keeps its settings elsewhere).")
    for d in log_dirs():
        for name in ("mcp-server-assistant-x.log",):
            p = os.path.join(d, name)
            if os.path.exists(p):
                out.append(f"\nLast lines of `{p}`:\n```\n{''.join(tail(p, 120)).strip()}\n```")
        p = os.path.join(d, "mcp.log")
        if os.path.exists(p):
            lines = [l for l in tail(p, 5000) if "assistant-x" in l][-40:]
            if lines:
                out.append(f"\nLines about assistant-x from `{p}`:\n```\n{''.join(lines).strip()}\n```")
    return "\n\n".join(out)


# ---------------------------------------------------------------- self-test
def step(rows, name, fn):
    t = time.time()
    try:
        note = fn() or ""
        rows.append((name, "ok", f"{time.time() - t:.2f} s", note))
        return True
    except Exception as e:
        rows.append((name, "**FAILED**", f"{time.time() - t:.2f} s", f"{type(e).__name__}: {e}"))
        debuglog.log_error(f"debug report: {name}", e)
        hints.append(f'Self-test "{name}" failed: {type(e).__name__}: {e}')
        return False


def mcp_check():
    """Start the MCP server exactly as a client would and call two tools over stdio."""
    import asyncio
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

    async def go():
        env = dict(os.environ, HF_HUB_OFFLINE=os.environ.get("HF_HUB_OFFLINE", "1"), PYTHONUTF8="1")
        p = StdioServerParameters(command=sys.executable, args=["-m", "assistant_x.server.mcp_server"], env=env)
        async with stdio_client(p) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = [t.name for t in (await s.list_tools()).tools]
                res = await s.call_tool("search_library", {"query": TEST_QUERY, "k": 3})
                text = getattr(res.content[0], "text", "")
                if "command failed" in text or getattr(res, "isError", False):
                    raise RuntimeError(text[:300])
                return f"commands: {', '.join(tools)}; answer of {len(text)} chars, start: {text[:80]!r}"

    return asyncio.run(asyncio.wait_for(go(), 180))


@section("Self-test")
def selftest(quick):
    rows, ctx = [], {}
    if not step(rows, "loading the search modules", lambda: ctx.update(mod=__import__("search"))):
        return table(rows, ("Step", "Result", "Time", "Details"))
    step(rows, "opening the base", lambda: ctx.update(lib=ctx["mod"].Library()) or f"fragments {ctx['lib']._total}")
    lib = ctx.get("lib")
    if lib:
        step(
            rows,
            "search by words",
            lambda: f"{len(lib.word_search(TEST_QUERY))} candidates; FTS query: {lib.fts_query(TEST_QUERY)[:120]}",
        )
        if quick:
            rows.append(("search by meaning", "skipped", "", "started with --quick"))
        elif lib.has_vectors():
            step(
                rows,
                "loading the embedding model",
                lambda: (
                    lib.embedder(),
                    lib._load_vectors(),
                    f"device {lib.embedder().device}, FAISS index {'yes' if lib._load_vectors()[2] is not None else 'no'}",
                )[-1],
            )
            step(rows, "search by meaning", lambda: f"{len(lib.dense_search(TEST_QUERY))} candidates")
            if lib.may_rerank():
                step(rows, "reranking", lambda: f"{len(lib.search(TEST_QUERY, k=5, rerank=True))} results")
        else:
            rows.append(("search by meaning", "no embeddings", "", "vectors.f16 not found"))
        step(rows, "full search", lambda: "; ".join(f"{r['code']} PDF {r['page']}" for r in lib.search(TEST_QUERY, k=5)))

        def image():
            import pymupdf

            d = lib.con.execute("SELECT code FROM docs WHERE file LIKE '%.pdf' ORDER BY code LIMIT 1").fetchone()
            if not d:
                return "no PDF documents"
            path, why = lib.original(d["code"])
            if not path:
                raise FileNotFoundError(why)
            pdf = pymupdf.open(path)
            png = pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).tobytes("png")
            return f"{d['code']} page 1: {size(len(png))}"

        step(rows, "page image of an original", image)
    if not quick:
        step(rows, "MCP server (start and two calls)", mcp_check)
    return table(rows, ("Step", "Result", "Time", "Details"))


# ---------------------------------------------------------------- queries
@section("Queries to the library")
def queries():
    from assistant_x.search import query_log

    return query_log.summary(query_log.parse([debuglog.calls_path() + ".1", debuglog.calls_path()]), limit=60)


# ---------------------------------------------------------------- journal
@section("Failure journal (last entries)")
def journal():
    out = []
    if os.path.exists(debuglog.errors_path()):
        entries = open(debuglog.errors_path(), encoding="utf-8", errors="replace").read().split("=== ")[1:]
        out.append(f"Entries in failures.log: {len(entries)}; the last 20 below.")
        out.append("```\n" + "".join("=== " + e for e in entries[-20:]).strip() + "\n```")
    else:
        out.append("No failures logged.")
    if os.path.exists(debuglog.calls_path()):
        out.append("The last 40 calls (time, command, duration, result, arguments):")
        out.append("```\n" + "".join(tail(debuglog.calls_path(), 40)).strip() + "\n```")
    return "\n\n".join(out)


def main():
    ap = argparse.ArgumentParser(prog="assistant-x debug-report")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    print("Collecting the debug report… (the self-test with loading the models may take up to 1–2 minutes)", flush=True)
    now = datetime.datetime.now()
    os.makedirs(debuglog.log_dir(), exist_ok=True)
    path = os.path.join(debuglog.log_dir(), f"debug_report_{debuglog.pc_id()}_{now:%Y-%m-%d_%H%M}.md")
    steps = [
        ("Computer", computer, ()),
        ("Python and packages", python_env, ()),
        ("Search installation", installation, ()),
        ("Search base", base, ()),
        ("Claude Desktop connection", desktop, ()),
        ("Self-test", selftest, (a.quick,)),
        ("Queries to the library", queries, ()),
        ("Failure journal", journal, ()),
    ]
    parts = []

    def write(next_title=None):
        # rewritten after every section: if Python dies mid-way, the file still shows how far it got
        head = (
            f"# Debug report of the library search\n\n"
            f"Created: {now:%Y-%m-%d %H:%M:%S}, PC: {debuglog.pc_id()}, in {time.time() - t0:.0f} s.\n\n"
            f"The report holds the names of the PC and the user, folder paths and the texts of the last queries to the "
            f"library. It holds no content of the documents and no keys from the Claude settings.\n\n## What stands out\n\n"
            + ("\n".join(f"- {h}" for h in dict.fromkeys(hints)) or "- No obvious problems found.")
            + "\n"
        )
        tail_note = (
            f'\n**The report is incomplete: collecting stopped at the section "{next_title}".**\n' if next_title else ""
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(head + "\n" + "\n".join(parts) + tail_note)

    for title, fn, args in steps:
        write(title)
        print(f"  {title}…", flush=True)
        parts.append(fn(*args))
    write()
    print(f"\nDone: {path}\nPass this file on for a look.")
    if debuglog.may_open() and not a.no_open:
        try:
            subprocess.Popen(["explorer", f"/select,{path}"])
        except OSError:
            pass


if __name__ == "__main__":
    debuglog.run(main, "debug_report")
