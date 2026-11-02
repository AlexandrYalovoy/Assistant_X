# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jurisdictions of the documents in the answers of search_library (jurisdictions.json of the profile): the
documents of the 'home' jurisdictions answer; the 'extra' ones (the American standards of the oil and gas profile)
come after them as a supplement, in places of their own, never instead of them; a question that names a
jurisdiction ("Kazakh norms", "API") puts its documents first. A document takes the 'jurisdiction' of its card when
it has one, else the first jurisdiction whose pattern matches its designation (else the start of its title), else the
default. A profile without the file changes nothing. Standard library only."""

import functools, json, re

from assistant_x.core import config

FILE = "jurisdictions.json"


class Jurisdictions:
    def __init__(self, data):
        self.default = data.get("default", "")
        self.home = set(data.get("home") or [])
        self.extra = {k: int(v) for k, v in (data.get("extra") or {}).items()}
        self.rules = [
            (j["id"], [re.compile(p) for p in j.get("patterns") or []], j.get("ask") or [])
            for j in data.get("jurisdictions") or []
        ]

    def of(self, r):
        """The jurisdiction of a hit (or a card row): its own field, else its designation, else its title."""
        if r.get("jurisdiction"):
            return r["jurisdiction"]
        names = [x.strip() for x in (r.get("designation") or "").split(" / ") if x.strip()] or [(r.get("title") or "")]
        for jid, pats, _ in self.rules:
            if any(p.search(n) for p in pats for n in names):
                return jid
        return self.default

    def asked(self, query):
        """The jurisdictions a question names by their words (the start of a word of the question)."""
        words = re.findall(r"\w+", (query or "").lower())
        return [jid for jid, _, ask in self.rules if any(w.startswith(a) for a in ask for w in words)]

    def room(self):
        """The places the supplements may take after the k answers."""
        return sum(self.extra.values())

    def arrange(self, res, query, k):
        """The hits in the order of the jurisdictions: a named one first (the order of the search within it); else the
        home ones, k at most, then the supplements, each in its places, after them."""
        named = self.asked(query)
        if named:
            first = [r for r in res if self.of(r) in named]
            return first + [r for r in res if self.of(r) not in named]
        if not self.extra:
            return res
        main = [r for r in res if self.of(r) not in self.extra][:k]
        more, used = [], {}
        for r in res:
            j = self.of(r)
            if j in self.extra and used.get(j, 0) < self.extra[j]:
                used[j] = used.get(j, 0) + 1
                more.append(r)
        return main + more


@functools.lru_cache(maxsize=8)
def load(profile):
    """The jurisdictions of a profile (None when it has no jurisdictions.json)."""
    p = config.profile_file(FILE, {"profile": profile})
    return Jurisdictions(json.loads(p.read_text(encoding="utf-8"))) if p else None
