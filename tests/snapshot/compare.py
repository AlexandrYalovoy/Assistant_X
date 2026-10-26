# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compare two recognition snapshots (snapshot.py): constants changed or removed, constants that differ only in the
order inside a character class or in the order of alternatives (the languages joined in another order), and the
behaviour keys that differ. A clean result: "constants differing: 0 … behaviour keys differing: 0".

    python -m tests.snapshot.compare BEFORE.json AFTER.json
"""

import json, sys

a = json.load(open(sys.argv[1], encoding="utf-8"))
b = json.load(open(sys.argv[2], encoding="utf-8"))
sys.stdout.reconfigure(encoding="utf-8")
import re

ITEM = re.compile(r"\\.|.-.|.", re.S)


def canon(p):
    """A pattern with the items of every character class sorted: [A-ZА-Я] and [А-ЯA-Z] are the same class."""
    out, i = [], 0
    while i < len(p):
        if p[i] == "\\":
            out.append(p[i : i + 2])
            i += 2
            continue
        if p[i] == "[":
            j = i + 1
            if j < len(p) and p[j] == "^":
                j += 1
            k = j + (1 if j < len(p) and p[j] == "]" else 0)
            while k < len(p) and p[k] != "]":
                k += 2 if p[k] == "\\" else 1
            out.append(p[i:j] + "".join(sorted(ITEM.findall(p[j:k]))) + "]")
            i = k + 1
            continue
        out.append(p[i])
        i += 1
    return "".join(out)


def same(x, y):
    if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        if len(x) == 3 and x[0] == "<re>" and y[0] == "<re>":
            return x[2] == y[2] and canon(x[1]) == canon(y[1])
        return all(same(p, q) for p, q in zip(x, y))
    if isinstance(x, dict) and isinstance(y, dict):
        return x.keys() == y.keys() and all(same(x[k], y[k]) for k in x)
    return x == y


def split_alts(s):
    """Top-level alternatives of s, each with its groups' alternatives sorted the same way (recursively)."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            cur += s[i : i + 2]
            i += 2
            continue
        if ch == "[":
            j = s.index("]", i + 2)
            cur += s[i : j + 1]
            i = j + 1
            continue
        depth += ch == "("
        depth -= ch == ")"
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    return sorted(parts + [cur])


def groups_sorted(p):
    """The pattern with the alternatives of the top level and of every group sorted."""
    p = canon(p)

    # sort the alternatives inside every outermost group and at the top
    def norm(s):
        i, cur = 0, ""
        while i < len(s):
            ch = s[i]
            if ch == "\\":
                cur += s[i : i + 2]
                i += 2
                continue
            if ch == "[":
                j = s.index("]", i + 2)
                cur += s[i : j + 1]
                i = j + 1
                continue
            if ch == "(":
                d, j = 1, i + 1
                while d and j < len(s):
                    if s[j] == "\\":
                        j += 2
                        continue
                    if s[j] == "[":
                        j = s.index("]", j + 2) + 1
                        continue
                    d += s[j] == "("
                    d -= s[j] == ")"
                    j += 1
                inner = s[i + 1 : j - 1]
                pre = ""
                m = re.match(r"\?(?:[:=!]|<[=!]|P<\w+>|[aiLmsux]+[:)])", inner)
                if m:
                    pre, inner = m.group(0), inner[m.end() :]
                cur += "(" + pre + "|".join(norm(x) for x in sorted(split_alts(inner))) + ")"
                i = j
                continue
            cur += ch
            i += 1
        return cur

    fl = re.match(r"\(\?[aiLmsux]+\)", p)
    head, p = (fl.group(0), p[fl.end() :]) if fl else ("", p)
    return head + "|".join(sorted(norm(x) for x in split_alts(p)))


def same_reordered(x, y):
    if isinstance(x, list) and isinstance(y, list):
        if len(x) == 3 and x[:1] == ["<re>"] == y[:1]:
            return x[2] == y[2] and groups_sorted(x[1]) == groups_sorted(y[1])
        if len(x) != len(y):
            return False
        key = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True)
        xs, ys = sorted(x, key=key), sorted(y, key=key)
        return all(same(a1, b1) or same_reordered(a1, b1) for a1, b1 in zip(xs, ys)) or all(
            same(a1, b1) or same_reordered(a1, b1) for a1, b1 in zip(x, y)
        )
    return False


nc = nclass = norder = 0
for mod, consts in a["constants"].items():
    other = b["constants"].get(mod)
    if other is None:
        print("MODULE GONE", mod)
        continue
    for k, v in consts.items():
        if k not in other:
            print(f"REMOVED {mod}.{k}")
            nc += 1
        elif other[k] != v and same(v, other[k]):
            nclass += 1
        elif other[k] != v and same_reordered(v, other[k]):
            norder += 1
            print(f"REORDERED {mod}.{k} (the same alternatives, the languages in another order)")
        elif other[k] != v:
            print(
                f"CHANGED {mod}.{k}\n   before: {json.dumps(v, ensure_ascii=False)[:400]}\n   after:  {json.dumps(other[k], ensure_ascii=False)[:400]}"
            )
            nc += 1
nb = 0
for k, v in a["behaviour"].items():
    if b["behaviour"].get(k) != v:
        nb += 1
        x, y = json.dumps(v, ensure_ascii=False), json.dumps(b["behaviour"].get(k), ensure_ascii=False)
        i = next((i for i in range(min(len(x), len(y))) if x[i] != y[i]), min(len(x), len(y)))
        print(
            f"BEHAVIOUR {k} differs at {i}:\n   before: …{x[max(0, i - 150) : i + 150]}\n   after:  …{y[max(0, i - 150) : i + 150]}"
        )
print(
    f"constants differing: {nc}; only the order inside a character class: {nclass}; only the order of alternatives: {norder}; behaviour keys differing: {nb}"
)
