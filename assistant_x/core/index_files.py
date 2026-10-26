# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of an empty index, made once: the folders cards/ and texts/ with their notes, an empty CATALOG.md and
sources_to_update.md (both are made from the cards later: search/catalog.py). `assistant-x init` makes them, the
apply of an intake makes what is missing; nothing existing is ever overwritten here."""

import datetime
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "index"


def _write_new(path, text, made):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        made.append(path)


def ensure(index, date=None, templates=True):
    """Make the files and folders of index that are missing; templates: also the notes of the cards and texts
    folders. Returns the paths made."""
    from assistant_x.search import catalog

    index, date, made = Path(index), date or datetime.date.today().isoformat(), []
    for sub in ("cards", "texts"):
        if not (index / sub).is_dir():
            (index / sub).mkdir(parents=True, exist_ok=True)
            made.append(index / sub)
    for src in TEMPLATES.rglob("*") if templates else ():
        if src.is_file():
            _write_new(index / src.relative_to(TEMPLATES), src.read_text(encoding="utf-8"), made)
    _write_new(index / catalog.CATALOG, catalog.catalog_text({}, date), made)
    _write_new(index / catalog.UPDATES, catalog.updates_text({}, date), made)
    return made
