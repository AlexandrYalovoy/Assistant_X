# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quality report of the golden corpus: a table of every case and the totals, written to
tests/corpus/last_report.json; --baseline writes the totals as the new baseline of the mode (a deliberate step:
the tests compare every run with tests/corpus/baseline.json).

    python -m tests.corpus.report [--full] [--baseline] [--keep]

The temporary workspace of the run is removed at the end (--keep leaves it, and says where, to look into it).
"""

import atexit, gc, json, os, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE, LAST = HERE / "baseline.json", HERE / "last_report.json"


def isolate():
    """The corpus runs in a workspace of its own: nothing of the user's is read or written."""
    root = tempfile.mkdtemp(prefix="ax_corpus_report_")
    os.environ["AX_WORKSPACE"] = os.path.join(root, "ws")
    os.environ["AX_HEAVY_LOCK_FILE"] = os.path.join(root, "heavy.lock")
    os.environ["AX_SPEED_FILE"] = os.path.join(root, "speed.json")
    os.environ["AX_NO_OPEN"] = "1"
    os.makedirs(os.environ["AX_WORKSPACE"], exist_ok=True)
    with open(os.path.join(os.environ["AX_WORKSPACE"], "assistant_x.toml"), "w", encoding="utf-8") as f:
        f.write('profile = "oil-gas-ru"\n')
    return root


def cleanup(root, keep=False):
    """Remove the workspace of the run (keep: leave it and say where). The bases and states it opened are let go
    first; what Windows still holds is removed when the process ends."""
    if keep:
        print(f"the workspace of the run is kept: {root}")
        return
    gc.collect()
    shutil.rmtree(root, ignore_errors=True)
    if os.path.exists(root):
        atexit.register(shutil.rmtree, root, True)


def table(rep):
    lines = [
        f"Corpus ({rep['mode']}):",
        "",
        f"{'case':22} {'phrases':8} {'headings':24} {'OCR':6} {'verdict':8} {'s':>6}  meta",
    ]
    for name, m in rep["cases"].items():
        lines.append(
            f"{name:22} {m.get('phrases', ''):8} {m.get('headings', ''):24} {str(m.get('ocr_accuracy', '')):6} "
            f"{('ok' if m.get('verdict') == 'ok' else 'WRONG' if m.get('verdict') else ''):8} "
            f"{str(m.get('seconds', '')):>6}  {m.get('meta', '')}"
        )
        if m.get("verdict") not in (None, "ok"):
            lines.append(f"{'':22} verdict: {m['verdict']}")
    lines += ["", "Totals: " + ", ".join(f"{k} {v}" for k, v in rep["totals"].items())]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = "full" if "--full" in argv else "fast"
    root = isolate()
    from tests.corpus import metrics

    try:
        rep = metrics.measure(mode, os.path.join(root, "corpus"))
    finally:
        cleanup(root, keep="--keep" in argv)
    sys.stdout.reconfigure(encoding="utf-8")
    print(table(rep))
    LAST.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    if "--baseline" in argv:
        base[mode] = {k: v for k, v in rep["totals"].items() if k in metrics.KEYS}
        BASELINE.write_text(json.dumps(base, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"baseline of {mode} written to {BASELINE}")
    else:
        low = metrics.below(rep, base.get(mode))
        print("Below the baseline: " + ("; ".join(f"{k} {v} < {b}" for k, v, b in low) if low else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
