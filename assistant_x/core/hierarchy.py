# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hierarchy of the documents: which kind of document rules over which (the constitution over the laws, a
national standard over an organization standard, a norm over a handbook). The answers list the requirements level by
level, the highest first, and say on a conflict that the higher level wins; the search gives a higher level a small
lift among close candidates (retrieval.Library.rerank), never a filter.

The levels are data: hierarchy.json of the profile (the patterns of the designations of its country), the default of
the general profile when the profile has none, and the user's own hierarchy.json in the workspace over both
(library_hierarchy writes it when the user names their hierarchy). A document is placed by its designation (else the
start of its title): the first level with a matching pattern, then its shelf (a book, a journal), else UNPLACED.

    {"levels": [{"rank": 5, "name": {"en": "National standards", "ru": "…"}, "patterns": ["^GOST\\b", …]}, …],
     "shelves": {"L": 10, "J": 10}, "unplaced": 9}

Standard library only."""

import json, re
from pathlib import Path

FILE = "hierarchy.json"
UNPLACED = 9  # a document no pattern places and no shelf: just above the books
DEFAULT = Path(__file__).resolve().parent.parent / "profiles" / "general" / FILE


class Hierarchy:
    def __init__(self, data, source=""):
        self.source = source
        self.levels = []
        for lv in data.get("levels") or []:
            rank = float(lv["rank"])
            name = lv.get("name") or {}
            name = name if isinstance(name, dict) else {"en": str(name)}
            pats = [re.compile(p) for p in lv.get("patterns") or []]
            self.levels.append((rank, name, pats))
        self.levels.sort(key=lambda x: x[0])
        self.shelves = {str(k): float(v) for k, v in (data.get("shelves") or {}).items()}
        self.unplaced = float(data.get("unplaced", UNPLACED))

    def rank(self, designation="", title="", code=""):
        """The level of a document: 1 is the highest; the designation decides (each of "A / B"), else the title."""
        names = [x.strip() for x in (designation or "").split(" / ") if x.strip()] or [(title or "").strip()]
        for rank, _, pats in self.levels:
            if any(p.search(n) for p in pats for n in names):
                return rank
        shelf = (code or "")[:1]
        return self.shelves.get(shelf, self.unplaced)

    def name(self, rank, lang="en"):
        for r, name, _ in self.levels:
            if r == rank:
                return name.get(lang) or name.get("en") or str(r)
        return str(rank)

    def table(self, lang="en"):
        """[(rank, name)] of the levels, the highest first."""
        return [(r, n.get(lang) or n.get("en") or str(r)) for r, n, _ in self.levels]


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check(data):
    """'' when data is a hierarchy that loads, else why not (library_hierarchy refuses to write a bad one)."""
    if not isinstance(data, dict) or not isinstance(data.get("levels"), list) or not data["levels"]:
        return 'a hierarchy is {"levels": [{"rank": 1, "name": {...}, "patterns": ["^..."]}, ...]}'
    for lv in data["levels"]:
        if not isinstance(lv, dict) or "rank" not in lv:
            return f"every level needs a rank: {lv!r}"
        try:
            float(lv["rank"])
            for p in lv.get("patterns") or []:
                re.compile(p)
        except (TypeError, ValueError, re.error) as e:
            return f"level {lv.get('rank')!r}: {e}"
    return ""


def load(root=None, profile_dir=None):
    """The hierarchy in force: the workspace's own hierarchy.json, else the profile's, else the default."""
    for p in ([Path(root) / FILE] if root else []) + ([Path(profile_dir) / FILE] if profile_dir else []) + [DEFAULT]:
        data = read(p) if p.is_file() else None
        if data and not check(data):
            return Hierarchy(data, str(p))
    return Hierarchy({}, "")
