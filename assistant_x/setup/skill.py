# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The skill of a profile, from one core for every app: assistant_x/templates/skill/SKILL.md (the full rules) and
guide.md (the short ones) with the shared parts (safety.md), the "skill" texts of the profile (the title, the
description, the example question, the role, the best practice to rely on) and the words of the app family put in.

    claude  Claude Desktop (a zip the user uploads) and Claude Code: the only variant that names Claude
    agent   Codex and the ChatGPT desktop app, DeepSeek Harness: the same SKILL.md format, no app named
    guide   the short rules: the answer of the tool library_guide, the system prompt of an LM Studio preset

Every SKILL.md carries a stamp under its header: the version of Assistant X and the hash of its text, so an outdated
skill is found and one edited by hand is told from it (clients/skills.py).

    assistant-x skill [--profile NAME] [--app claude|agent|guide] [--out FOLDER]
        (default: the profile of the workspace, claude, <workspace>/skill)

Claude: zip the folder it writes (it holds SKILL.md) and upload it: Settings → Capabilities → Skills → Upload."""

import argparse, hashlib, re, sys
from pathlib import Path

from assistant_x.core import config, workspace

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "skill"
TEMPLATE = TEMPLATES / "SKILL.md"
GUIDE = TEMPLATES / "guide.md"
PARTS = ("safety",)  # templates/skill/<part>.md put into {{<part>}} of every variant: one text for all
WRAPPERS = {
    "claude": {
        "app": "Claude",
        "troubleshoot": (
            "close Claude completely (the icon by the clock → Quit) and open it again; if that does not help, run\n"
            '`assistant-x connect --check` (or `Setup.bat` once more); if the answer is "Library command failed…", run\n'
            "`scripts\\debug_report.bat` and look at the report it creates."
        ),
    },
    "agent": {
        "app": "this app",
        "troubleshoot": (
            "run `assistant-x connect --check` in a terminal (it says which part fails) and restart the app; if the\n"
            'answer is "Library command failed…", run `assistant-x debug-report` and look at the report it creates.'
        ),
    },
}
STAMP = "<!-- assistant-x skill {version} sha256:{digest} -->"
STAMP_RX = re.compile(r"^<!-- assistant-x skill (\S+) sha256:([0-9a-f]{12}) -->\n", re.M)


def fill(text, profile=None, app="claude"):
    """A template with the parts, the words of the app family and the "skill" texts of a profile put in (None: the
    profile of the workspace)."""
    raw = {"profile": profile} if profile else config.load()[1]
    texts = config.profile_info(raw).get("skill") or config.profile_info({"profile": config.PROFILE})["skill"]
    shelves = "\n".join(
        f"  - `{s['letter']}` {' / '.join(s['name'].values())} — {s['about']} (types: {', '.join(s['doc_types'])})"
        for s in config.sections(raw)
    )
    parts = {p: (TEMPLATES / f"{p}.md").read_text(encoding="utf-8").strip() for p in PARTS}
    words = WRAPPERS[app]
    for k, v in {
        **parts,
        **words,
        **texts,
        "shelves": shelves,
        "card_languages": ", ".join(config.card_languages(raw)),
    }.items():
        text = text.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{(\w+)\}\}", text)
    if left:
        sys.exit(f"The profile has no skill texts for: {', '.join(sorted(set(left)))}")
    return text


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def stamp(text):
    """text with the stamp put under its front matter (or on top)."""
    from assistant_x import __version__

    line = STAMP.format(version=__version__, digest=digest(text)) + "\n"
    m = re.match(r"---\n.*?\n---\n", text, re.S)
    return text[: m.end()] + line + text[m.end() :] if m else line + text


def stamped(text):
    """(version, unchanged) of a stamped text: unchanged is False when it was edited after it was written;
    (None, False) without a stamp."""
    m = STAMP_RX.search(text)
    if not m:
        return None, False
    return m.group(1), digest(text[: m.start()] + text[m.end() :]) == m.group(2)


def render(profile=None, app="claude"):
    """The text of SKILL.md for a profile (None: the profile of the workspace) and an app family, stamped."""
    return stamp(fill(TEMPLATE.read_text(encoding="utf-8"), profile, app))


def guide(profile=None):
    """The short rules of the answers with the shelves of the library (the tool library_guide)."""
    return fill(GUIDE.read_text(encoding="utf-8"), profile, "agent").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x skill", description="Write the skill of a profile")
    ap.add_argument("--profile", help=f"one of: {', '.join(config.profiles())} (default: the profile of the workspace)")
    ap.add_argument("--app", choices=("claude", "agent", "guide"), default="claude")
    ap.add_argument("--out", help="the folder of SKILL.md (default: <workspace>/skill)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else workspace.current().root / "skill"
    out.mkdir(parents=True, exist_ok=True)
    if a.app == "guide":
        (out / "system-prompt.md").write_text(guide(a.profile) + "\n", encoding="utf-8", newline="\n")
        print(f"Written {out / 'system-prompt.md'}: the system prompt of an LM Studio preset (or any chat app).")
        return 0
    (out / "SKILL.md").write_text(render(a.profile, a.app), encoding="utf-8", newline="\n")
    where = "upload it in Claude: Settings → Capabilities → Skills" if a.app == "claude" else "copy it into the skills"
    print(f"Written {out / 'SKILL.md'}. Zip the folder {out} and {where}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
