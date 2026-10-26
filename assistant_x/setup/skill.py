# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Claude skill of a profile: assistant_x/templates/skill/SKILL.md with the "skill" texts of the profile (the
title, the description, the example question, the role, the best practice to rely on) put in.

    assistant-x skill [--profile NAME] [--out FOLDER]   (default: the profile of the workspace, <workspace>/skill)

Zip the folder it writes (it holds SKILL.md) and upload it in Claude: Settings → Capabilities → Skills → Upload."""

import argparse, sys
from pathlib import Path

from assistant_x.core import config, workspace

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "skill" / "SKILL.md"


def render(profile=None):
    """The text of SKILL.md for a profile (None: the profile of the workspace)."""
    raw = {"profile": profile} if profile else config.load()[1]
    texts = config.profile_info(raw).get("skill") or config.profile_info({"profile": config.PROFILE})["skill"]
    text = TEMPLATE.read_text(encoding="utf-8")
    shelves = "\n".join(
        f"  - `{s['letter']}` {' / '.join(s['name'].values())} — {s['about']} (types: {', '.join(s['doc_types'])})"
        for s in config.sections(raw)
    )
    for k, v in {**texts, "shelves": shelves, "card_languages": ", ".join(config.card_languages(raw))}.items():
        text = text.replace("{{" + k + "}}", v)
    left = [p for p in ("title", "description", "example", "role", "practice") if "{{" + p + "}}" in text]
    if left:
        sys.exit(f"The profile has no skill texts for: {', '.join(left)}")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assistant-x skill", description="Write the Claude skill of a profile")
    ap.add_argument("--profile", help=f"one of: {', '.join(config.profiles())} (default: the profile of the workspace)")
    ap.add_argument("--out", help="the folder of SKILL.md (default: <workspace>/skill)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else workspace.current().root / "skill"
    out.mkdir(parents=True, exist_ok=True)
    (out / "SKILL.md").write_text(render(a.profile), encoding="utf-8", newline="\n")
    print(f"Written {out / 'SKILL.md'}. Zip the folder {out} and upload it in Claude: Settings → Capabilities → Skills.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
