# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""index\packages.json: the base packages installed into this library.

    {"packages": [{"id", "version", "name": {en, ru}, "installed": date, "documents": n, "manifest_sha": sha256 of the
                   axbase.json of the package}]}

One entry per package id (an update replaces it). Written at once (a temporary file and os.replace)."""

import json
from pathlib import Path

from assistant_x.core.txn import write_whole

FILE = "packages.json"


def open_transactions(data):
    """The base install, update and remove of the workspace that were interrupted and wait for --resume or --rollback
    (their journals in <data>/w/<hash>/install.journal.json): ["install of <id> <version>", …]. While one is open the
    intake builds and applies nothing, and the other way round (an install checks the batches of the intake)."""
    out = []
    for p in sorted(Path(data, "w").glob("*/install.journal.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        out.append(f"{d.get('kind', 'install')} of {d.get('id', '?')} {d.get('version', '')}".rstrip())
    return out


def path(index):
    return Path(index) / FILE


def load(index):
    """[entries] of the installed packages ([] when there is none or the file does not read)."""
    try:
        data = json.loads(path(index).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data.get("packages") or [] if isinstance(p, dict) and p.get("id")]


def get(index, package_id):
    return next((p for p in load(index) if p["id"] == package_id), None)


def put(index, entry):
    """Add or replace the entry of a package (by its id)."""
    if not entry.get("id") or not entry.get("version"):
        raise ValueError("a package entry needs an id and a version")
    rest = [p for p in load(index) if p["id"] != entry["id"]]
    _save(index, sorted(rest + [dict(entry)], key=lambda p: p["id"]))


def remove(index, package_id):
    """Forget a package; True when it was there."""
    have = load(index)
    rest = [p for p in have if p["id"] != package_id]
    if len(rest) != len(have):
        _save(index, rest)
    return len(rest) != len(have)


def _save(index, packages):
    path(index).parent.mkdir(parents=True, exist_ok=True)
    write_whole(path(index), json.dumps({"packages": packages}, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
