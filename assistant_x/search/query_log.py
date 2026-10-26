# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Review of the call journal (debug/calls.log): what the library was asked, where the search answered weakly,
where Claude rephrased for long, which calls were slow. Writes debug/query_log_<PC id>_<date>.md.
Usage: python -m assistant_x.search.query_log [calls.log ...] [--weak 0.5] [--no-open]
Without arguments it takes the journal of this PC; journals of other PCs can be given."""

import argparse, datetime, json, math, os, re, statistics, subprocess

from assistant_x.core import debuglog

WEAK = 0.5  # closeness of the best fragment below this: the library hardly covers the question
GAP = 180  # searches less than 3 minutes apart belong to one question
SLOW = 5.0  # seconds
SERVER_START = {"server start"}  # the line of a server start
WORDS_RX = re.compile(r"by words (\d+)")
CLOSE_RX = re.compile(r"closeness (-?[\d.]+)")
FOUND_RX = re.compile(r"found (\d+)")
TOP_RX = re.compile(r"found \d+: ([^;]*)")


def parse(paths):
    calls = []
    for path in paths:
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            parts = line.rstrip("\n").split("\t", 5)
            if len(parts) < 5:
                continue
            when, tool, ms, ok, args = parts[:5]
            note = parts[5] if len(parts) > 5 else ""
            try:
                t = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
                sec = float(ms.split()[0]) / 1000
            except ValueError:
                continue
            try:
                a = json.loads(args)
            except ValueError:  # the journal cuts long arguments: take the query out by hand
                m = re.search(r'"query":\s*"((?:[^"\\]|\\.)*)', args)
                a = {"query": json.loads(f'"{m.group(1)}"') if m else ""}
            c = dict(time=t, tool=tool, sec=sec, ok=ok == "ok", args=a if isinstance(a, dict) else {}, note=note)
            m = WORDS_RX.search(note)
            c["words"] = int(m.group(1)) if m else None
            m = CLOSE_RX.search(note)
            c["close"] = float(m.group(1)) if m else None
            m = FOUND_RX.search(note)
            c["found"] = int(m.group(1)) if m else None
            m = TOP_RX.search(note)
            c["top"] = m.group(1).strip() if m else ""
            calls.append(c)
    calls.sort(key=lambda c: c["time"])
    return calls


def table(rows, head):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in r) + " |" for r in rows]
    return "\n".join(out)


def is_weak(c, weak):
    return c["ok"] and (c["found"] == 0 or c["words"] == 0 or (c["close"] is not None and c["close"] < weak))


def summary(calls, weak=WEAK, limit=300):
    """Markdown body of the review (also used as a section of the debug report)."""
    if not calls:
        return "No calls in the journal."
    out = [
        f"Period: {calls[0]['time']:%Y-%m-%d %H:%M} – {calls[-1]['time']:%Y-%m-%d %H:%M}, entries {len(calls)}, "
        f"server starts {sum(c['tool'] in SERVER_START for c in calls)}."
    ]
    rows = []
    for tool in sorted({c["tool"] for c in calls} - SERVER_START):
        cs = [c for c in calls if c["tool"] == tool]
        secs = sorted(c["sec"] for c in cs)
        rows.append(
            (
                tool,
                len(cs),
                sum(not c["ok"] for c in cs),
                f"{statistics.median(secs):.2f} s",
                f"{secs[math.ceil(0.95 * len(secs)) - 1]:.2f} s",
                f"{secs[-1]:.2f} s",
            )
        )
    out.append(table(rows, ("Command", "Calls", "Failures", "Median", "95 %", "Longest")))

    searches = [c for c in calls if c["tool"] == "search_library" and c["args"].get("query")]
    rated = [c for c in searches if c["close"] is not None or c["words"] is not None]
    weak_list = [c for c in searches if is_weak(c, weak)]
    out.append(
        f"\n### Weak queries\n\nThe library seems to know the topic poorly: the best fragment by meaning is closer "
        f"than {weak:.2f}, or nothing was found. These are candidates for new documents or for synonyms.txt. "
        f"Rated queries: {len(rated)} of {len(searches)} (old journal entries without a rating are not counted)."
    )
    if weak_list:
        out.append(
            table(
                [
                    (
                        f"{c['time']:%m-%d %H:%M}",
                        c["args"]["query"][:150],
                        c["words"] if c["words"] is not None else "",
                        f"{c['close']:.2f}" if c["close"] is not None else "",
                        c["top"][:60],
                    )
                    for c in weak_list[-60:]
                ],
                ("When", "Query", "By words", "Closeness", "What was found"),
            )
        )
    else:
        out.append("No weak queries.")

    groups, cur = [], []
    for c in searches:
        if cur and (c["time"] - cur[-1]["time"]).total_seconds() > GAP:
            groups.append(cur)
            cur = []
        cur.append(c)
    if cur:
        groups.append(cur)
    long = [g for g in groups if len(g) >= 4]
    out.append(
        f"\n### Long searches\n\nQueries with pauses under {GAP // 60} minutes count as one question. "
        f"Four searches or more in a row mean that what was needed was not found at once. Questions in all "
        f"{len(groups)}, long ones {len(long)}."
    )
    for g in long[-20:]:
        out.append(
            f"- {g[0]['time']:%m-%d %H:%M}, searches {len(g)}: " + " → ".join(f'"{c["args"]["query"][:80]}"' for c in g[:8])
        )

    slow = [c for c in calls if c["sec"] >= SLOW and c["tool"] not in SERVER_START]
    out.append(
        f"\n### Slow calls (longer than {SLOW:.0f} s)\n\nThe first search after Claude starts may wait for the model "
        f"to load (up to 10–15 s), that is normal."
    )
    out.append(
        table(
            [
                (
                    f"{c['time']:%m-%d %H:%M:%S}",
                    c["tool"],
                    f"{c['sec']:.1f} s",
                    json.dumps(c["args"], ensure_ascii=False)[:120],
                )
                for c in slow[-30:]
            ],
            ("When", "Command", "Time", "Arguments"),
        )
        if slow
        else "None."
    )

    seen = {}
    for c in searches:
        q = re.sub(r"\s+", " ", c["args"]["query"]).strip()
        s = seen.setdefault(q.lower(), dict(q=q, n=0, last=c["time"], close=None))
        s["n"] += 1
        s["last"] = c["time"]
        s["close"] = c["close"] if c["close"] is not None else s["close"]
    uniq = sorted(seen.values(), key=lambda s: s["last"], reverse=True)[:limit]
    out.append(f"\n### All queries (the last {len(uniq)}, repeats joined)")
    out.append(
        table(
            [
                (s["q"][:200], s["n"], f"{s['last']:%m-%d %H:%M}", f"{s['close']:.2f}" if s["close"] is not None else "")
                for s in uniq
            ],
            ("Query", "Times", "Last", "Closeness"),
        )
    )
    firsts = [g[0]["args"]["query"].strip() for g in groups][-40:]
    if firsts:
        out.append(
            "\n### Draft for questions.md\n\nThe first query of every question. Paste the lines you need into the "
            'table of questions.md and put where the right answer is instead of "?" (e.g. `L-00015:306-312`). '
            'eval.py skips the lines with "?".\n'
        )
        out.append("```\n" + "\n".join(f"| {q.replace('|', '/')} | ? |" for q in dict.fromkeys(firsts)) + "\n```")
    return "\n\n".join(out)


def main():
    ap = argparse.ArgumentParser(prog="assistant-x query-log")
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--weak", type=float, default=WEAK)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    logs = a.logs or [debuglog.calls_path() + ".1", debuglog.calls_path()]
    calls = parse(logs)
    now = datetime.datetime.now()
    path = os.path.join(debuglog.log_dir(), f"query_log_{debuglog.pc_id()}_{now:%Y-%m-%d_%H%M}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            f"# Review of the queries to the library\n\nCreated {now:%Y-%m-%d %H:%M}, PC {debuglog.pc_id()}. Journals: "
            + ", ".join(f"`{p}`" for p in logs if os.path.exists(p))
            + "\n\n"
            + summary(calls, a.weak)
            + "\n"
        )
    searches = [c for c in calls if c["tool"] == "search_library"]
    print(
        f"Calls: {len(calls)}, searches: {len(searches)}, weak: {sum(is_weak(c, a.weak) for c in searches)}.\nDone: {path}"
    )
    if debuglog.may_open() and not a.no_open:
        try:
            subprocess.Popen(["explorer", f"/select,{path}"])
        except OSError:
            pass


if __name__ == "__main__":
    debuglog.run(main, "query_log")
