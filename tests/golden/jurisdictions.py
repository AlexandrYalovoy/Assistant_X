# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdictions of the hits of search_library on the library of the workspace (mcp_server.find_fragments):
a plain question must keep its home answer (Russian, EAEU, Kazakh, international documents) on top with the American
standards after it; a question naming Kazakhstan must have the Kazakh documents first. Measure again when the
American or the Kazakh norms come into the library.

    python tests/golden/jurisdictions.py"""

import os, sys

CASES = [
    ("plain", "как выбрать диаметр промыслового газопровода по скорости газа"),
    ("plain", "допустимая скорость нефти на всасывании насоса"),
    ("KZ", "что требуют казахстанские нормы к промысловым трубопроводам"),
]


def main():
    from assistant_x.search import jurisdiction
    from assistant_x.server import mcp_server as m

    m.lib().warm_up()
    jur = jurisdiction.load(m.lib().cfg.get("profile"))
    bad = 0
    for kind, q in CASES:
        res = m.find_fragments(q, 8, {})
        js = [jur.of(r) for r in res]
        print(f"{kind:5} {q}\n      " + " ".join(f"{r['code']}:{j}" for r, j in zip(res, js)))
        if kind == "plain":
            first_us = next((i for i, j in enumerate(js) if j in jur.extra), len(js))
            bad += any(j not in jur.extra for j in js[first_us:] if not res[js.index(j)].get("key"))
        elif kind == "KZ" and "KZ" in js:
            bad += js[0] != "KZ"
    print("in order" if not bad else f"{bad} case(s) out of order")
    return 1 if bad else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
