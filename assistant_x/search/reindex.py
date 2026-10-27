# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The base recalculation after an intake: build_index, then embed for the new fragments (intake_reindex starts it in
the background). Each step writes where it is to the progress file of AX_PROGRESS (intake_status shows it):

    python -m assistant_x.search.reindex [--cpu]

    {"stage": "build_index" | "embed", "done": n, "total": m, "updated": time}

At the end <the folder of the base>/reindex_last.json says what the last recalculation did: {started, finished,
fragments (of the base), embedded (new vectors), per_second (of the embeddings), device} (intake_reindex answers with
it when the base is up to date)."""

import datetime, json, os, sys, time

from assistant_x.core import proc
from assistant_x.core.progress import PROGRESS, read_progress, write_progress  # noqa: F401 — read by the server

LAST = "reindex_last.json"


def last_path(cfg):
    """reindex_last.json beside the base of the settings."""
    return os.path.join(os.path.dirname(cfg["db"]), LAST)


def read_last(cfg):
    try:
        with open(last_path(cfg), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, KeyError):
        return None


def counts(db):
    """(fragments of the base, fragments without a meaning vector); (0, 0) without a base."""
    from assistant_x.core.common import connect

    if not os.path.exists(db):
        return 0, 0
    con = connect(db, readonly=True)
    try:
        return tuple(con.execute("SELECT count(*), count(*) - count(vec_row) FROM chunks").fetchone())
    finally:
        con.close()


def write_last(cfg, started, embed_s, missing_before, device):
    """reindex_last.json of a finished recalculation."""
    total, missing = counts(cfg["db"])
    done = max(0, missing_before - missing)
    data = {
        "started": datetime.datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "finished": datetime.datetime.now().isoformat(timespec="seconds"),
        "fragments": total,
        "embedded": done,
        "per_second": round(done / embed_s, 1) if done and embed_s > 0 else None,
        "device": device,
    }
    try:
        with open(last_path(cfg) + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(last_path(cfg) + ".tmp", last_path(cfg))
    except OSError:
        pass
    return data


def _device(before, after, cpu):
    """The kind of device the embeddings ran on: the one whose measured speed embed.py has just written."""
    changed = [k for k, v in (after.get("fragments") or {}).items() if (before.get("fragments") or {}).get(k) != v]
    return changed[0] if changed else ("cpu" if cpu else None)


def main(argv=None):
    from assistant_x.core import gpu_guard
    from assistant_x.core.common import load_config

    argv = sys.argv[1:] if argv is None else argv
    if {"-h", "--help"} & set(argv):  # the options only: --help once built the base in the middle of a redo
        print(__doc__)
        return 0
    from assistant_x.core import lock

    with lock.heavy_task("reindex", wait=True):  # build_index and embed under it pass through
        return _run(argv, gpu_guard, load_config)


def _run(argv, gpu_guard, load_config):
    py, started = sys.executable, time.time()
    write_progress("build_index")
    rc = proc.call([py, "-m", "assistant_x.search.build_index"])
    if rc:
        return rc
    cfg = load_config()
    missing, speeds = counts(cfg["db"])[1], gpu_guard.speeds()
    write_progress("embed")
    t0 = time.time()
    rc = proc.call([py, "-m", "assistant_x.search.embed", *argv])
    if rc == 0:
        write_last(cfg, started, time.time() - t0, missing, _device(speeds, gpu_guard.speeds(), "--cpu" in argv))
    return rc


if __name__ == "__main__":
    sys.exit(main())
