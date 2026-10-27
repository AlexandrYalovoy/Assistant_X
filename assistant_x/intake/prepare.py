# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Preparing inbox before a batch (intake run, step 1): service files and personal papers set aside, archives
unpacked beside them, letters and Excel to _to_delete; the hashes of the library for the SHA duplicates."""

import collections, hashlib, os, re
from pathlib import Path

from assistant_x.core import lang
from assistant_x.intake import config as intake_cfg
from assistant_x.core import journal

from assistant_x.intake.tools import unpack
from assistant_x.core.formats import file_kind
from assistant_x.core.formats import natural_key
from assistant_x.intake.batch import SKIP_FILES, say, today, win


# ---------- preparing inbox ----------


def walk(inbox):
    """(full path, rel with /) of the files of inbox outside the service folders."""
    top = intake_cfg.lp(inbox)
    for dp, dns, fns in os.walk(top):
        if os.path.normcase(os.path.abspath(dp)) == os.path.normcase(os.path.abspath(top)):
            dns[:] = [d for d in dns if d not in intake_cfg.SERVICE]
        dns.sort(key=natural_key)  # "Chapter 2" before "Chapter 10": the tids follow the order of a book
        for f in sorted(fns, key=natural_key):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, top).replace("\\", "/")
            if f.lower() in SKIP_FILES:
                continue
            yield p, rel


THICK = 800  # pages: a document past it gets 8 GB and goes alone
# personal papers by the name of a file or a folder (BZ1): not opened, not recognised, straight to _to_delete.
# The words of the language packs (personal_papers: land register, insurance number, tax, income statement…); not the
# bare word for a passport: 04_Datasheets holds passports of equipment. [intake] personal_words replaces the list.
PERSONAL = tuple(lang.words("personal_papers"))


# the folders of a kit of a national standard and the names of its pages (lang/<code>/intake.json)
KIT = lang.table("kit_folders")
KIT_WORDS = {
    k: next((lang.get(c, "kit_" + k) for c in lang.active() if lang.get(c, "kit_" + k)), "(?!)")
    for k in ("not_main", "plan_of_measures", "approval", "signed_title", "plan", "explanatory", "register")
}
KIT_RX = re.compile(
    r"(.*?)/(" + "|".join(re.escape(KIT[k]) for k in ("file", "scan", "supplement") if k in KIT) + ")/" if KIT else "(?!)"
)  # no pack names the folders of a kit: no kit


def personal(cfg, rel):
    """The stop word found in the name of a file or of one of its folders, or None."""
    words = cfg.get("personal_words") or PERSONAL
    m = re.search("(?i)(" + "|".join(words) + ")", rel)
    return m.group(1) if m else None


def macos(rel):
    """__MACOSX\\… and ._name: the resource forks a Mac puts into archives; not documents, no error either."""
    parts = rel.split("/")
    return "__MACOSX" in parts[:-1] or parts[-1].startswith("._")


def free_target(path):
    p, k = Path(path), 2
    while os.path.exists(intake_cfg.lp(p)):
        p, k = Path(path).with_name(f"{Path(path).stem}_{k}{Path(path).suffix}"), k + 1
    return p


def move_aside(cfg, full, rel, folder):
    """Move a file of inbox into a service folder, keeping its folders; the place for the journal."""
    dst = free_target(cfg.inbox / folder / "/".join(intake_cfg.safe_name(x) for x in rel.split("/")))
    os.makedirs(intake_cfg.lp(dst.parent), exist_ok=True)
    os.replace(full, intake_cfg.lp(dst))
    return "inbox\\" + win(str(dst.parent.relative_to(cfg.inbox))) + "\\"


def prepare(cfg, state, dry=False):
    """The attachments of letters taken out beside them (the letter then to _to_delete), archives unpacked beside them
    (the archive then to _to_delete). Returns the counts and the events written."""
    st = collections.Counter()
    events, problems = [], []
    letters(cfg, st, events, problems, dry)
    refused = set(state.get_meta("archives_refused", []))
    lim = cfg.unpack
    while True:
        archives = [(p, rel) for p, rel in walk(cfg.inbox) if unpack.is_archive(rel) and rel not in refused]
        if not archives:
            break
        for full, rel in archives:
            size = os.path.getsize(full)
            word = personal(cfg, rel)
            if word:  # not even unpacked
                st["personal"] += 1
                if dry:
                    say(f'  to delete (personal, "{word}"): {win(rel)}')
                    refused.add(rel)
                    continue
                place = move_aside(cfg, full, rel, "_to_delete")
                events.append(
                    [today(), "inbox\\" + win(rel), size, "—", "—", place, f'to delete: personal ("{word}" in the name)']
                )
                continue
            if dry:
                say(f"  unpack: {win(rel)}")
                refused.add(rel)
                continue
            rep = unpack.unpack(
                full,
                max_total=float(lim["max_total_gb"]) * unpack.GB,
                max_depth=int(lim["max_depth"]),
                sevenzip=cfg.sevenzip,
                timeout=cfg.timeouts["unpack"],
            )
            if rep["error"] and rep["kind"] == unpack.PASSWORD:  # not an error of the batch: nobody can open it here
                place = move_aside(cfg, full, rel, "_to_delete")
                events.append(
                    [today(), "inbox\\" + win(rel), size, "—", "—", place, "to delete: an archive with a password"]
                )
                st["archive_password"] += 1
                continue
            if rep["error"]:
                refused.add(rel)
                problems.append(f"archive not unpacked: {win(rel)} — {rep['error']}")
                tid = state.add(rel, size)
                state.update(tid, status="error", why=f"archive not unpacked: {rep['error']}")
                st["archive_failed"] += 1
                continue
            for item in rep["left"]:
                left = os.path.relpath(item["path"], intake_cfg.lp(cfg.inbox)).replace("\\", "/")
                if item.get("kind") == unpack.PASSWORD:
                    inner = os.path.getsize(item["path"])
                    place = move_aside(cfg, item["path"], left, "_to_delete")
                    events.append(
                        [
                            today(),
                            "inbox\\" + win(left),
                            inner,
                            "—",
                            "—",
                            place,
                            "to delete: a nested archive with a password",
                        ]
                    )
                    st["archive_password"] += 1
                    continue
                refused.add(left)
                tid = state.add(left, os.path.getsize(item["path"]))
                state.update(tid, status="error", why=f"nested archive not unpacked: {item['why']}")
                problems.append(f"nested archive not unpacked: {win(left)} — {item['why']}")
            dest = "inbox\\" + win(os.path.relpath(rep["dest"], intake_cfg.lp(cfg.inbox)))
            place = move_aside(cfg, full, rel, "_to_delete")
            events.append(
                [today(), "inbox\\" + win(rel), size, "—", "—", place, f"to delete: the archive is unpacked into {dest}"]
            )
            st["archives"] += 1
            st["archive_files"] += rep["files"]
        if dry:
            break
    if not dry:
        state.set_meta("archives_refused", sorted(refused))
    for full, rel in list(walk(cfg.inbox)):
        word = personal(cfg, rel)
        if word:  # before anything opens it
            st["personal"] += 1
            if dry:
                say(f'  to delete (personal, "{word}"): {win(rel)}')
                continue
            size = os.path.getsize(full)
            place = move_aside(cfg, full, rel, "_to_delete")
            events.append(
                [today(), "inbox\\" + win(rel), size, "—", "—", place, f'to delete: personal ("{word}" in the name)']
            )
            continue
        what = "a macOS service file" if macos(rel) else None
        if not what:
            continue
        st["macos"] += 1
        if dry:
            say(f"  to delete ({what}): {win(rel)}")
            continue
        size = os.path.getsize(full)
        place = move_aside(cfg, full, rel, "_to_delete")
        events.append([today(), "inbox\\" + win(rel), size, "—", "—", place, f"to delete: {what}"])
    if events:
        journal.append_events(cfg.index / "intake_events.tsv", events)
    return st, events, problems


def letters(cfg, st, events, problems, dry=False):
    """Every letter of inbox (.eml .msg .oft): its attachments go into a folder of its name beside it (they are documents
    of the batch, an archive among them is unpacked next), the letter itself to _to_delete. A letter attached to a
    letter comes out as an .eml and is taken apart in the next round."""
    from assistant_x.intake.tools import letters as letter_tool

    done = set()
    while True:
        found = [
            (p, rel)
            for p, rel in walk(cfg.inbox)
            if file_kind(rel) == "letter" and rel not in done and not personal(cfg, rel)
        ]
        if not found:
            return
        for full, rel in found:
            done.add(rel)
            if dry:
                say(f"  letter: its attachments beside it, the letter to delete: {win(rel)}")
                continue
            size = os.path.getsize(full)
            dest = free_target(Path(full).with_suffix(""))
            rep = letter_tool.extract(full, intake_cfg.lp(dest), intake_cfg.safe_name)
            if rep["error"]:
                problems.append(f"letter {win(rel)}: {rep['error']}")
            n = len(rep["files"])
            where = "inbox\\" + win(str(Path(dest).relative_to(cfg.inbox))) if n else ""
            skipped = f"; not taken out (an embedded item): {', '.join(rep['skipped'])[:200]}" if rep["skipped"] else ""
            place = move_aside(cfg, full, rel, "_to_delete")
            events.append(
                [
                    today(),
                    "inbox\\" + win(rel),
                    size,
                    "—",
                    "—",
                    place,
                    (f"to delete: a letter, its {n} attachments are in {where}" if n else "to delete: a letter") + skipped,
                ]
            )
            st["letters"] += 1
            st["letter_files"] += n
        if dry:
            return


# ---------- duplicates ----------


CODE_IN = re.compile(r"\b[A-Z]-\d{5}(?:-\d{2,3})?\b")  # a code in the status of an event ("duplicate of N-00012 …")


def known_hashes(cfg):
    """{first 16 of SHA-256: code or place} of the library (manifest.tsv) and of the events (or the old journal.md).
    Only the events of a file that is in the library count: accepted (its code), or a duplicate of a code; a file
    that failed, was rejected or sent to delete is no duplicate when it comes again, nor one the user took out of the
    library later (a "removed" event: assistant-x remove)."""
    from assistant_x.core.card import is_code
    from assistant_x.core.formats import event_kind

    out = {}
    for row in journal.read_events(cfg.index / "intake_events.tsv") or journal.parse_journal(
        (cfg.index / "journal.md").read_text(encoding="utf-8") if (cfg.index / "journal.md").exists() else ""
    ):
        if len(row) < 7 or not re.fullmatch(r"[0-9a-f]{16}", row[3]):
            continue
        kind = event_kind(row[6])
        if kind == "removed":
            out.pop(row[3], None)
            continue
        code = row[4] if is_code(row[4]) else None
        if kind == "duplicate" and not code:
            code = next(iter(CODE_IN.findall(row[6])), None)
        if kind in ("accepted", "duplicate") and code:
            out[row[3]] = code
    man = cfg.index / "manifest.tsv"
    if man.exists():
        for line in man.read_text(encoding="utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) == 5 and c[3]:
                out[c[3][:16]] = c[4] or c[0]
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(intake_cfg.lp(path), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
