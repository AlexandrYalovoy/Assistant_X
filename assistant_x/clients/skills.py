# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The skill of an app in its skills folder (<folder>/SKILL.md, setup/skill.py renders it): written when missing or
outdated; a SKILL.md edited by hand (its stamp no longer matches its text) is kept and the new one put beside it as
SKILL.md.new. Taken out on disconnect unless edited by hand."""

from pathlib import Path

from assistant_x import clients as K

FAMILY = {"claude_code": "claude"}  # every other app with a skills folder: the "agent" variant


def text_for(name):
    from assistant_x.setup import skill

    return skill.render(app=FAMILY.get(name, "agent"))


def state(name):
    """'missing' | 'current' | 'outdated' | 'edited' of the skill of an app (None: the app has no skills folder)."""
    from assistant_x.setup import skill

    d = K.app(name).skill_dir()
    if d is None:
        return None
    p = Path(d) / "SKILL.md"
    if not p.exists():
        return "missing"
    old = p.read_text(encoding="utf-8")
    _, intact = skill.stamped(old)
    if not intact:
        return "edited"
    return "current" if old == text_for(name) else "outdated"


def install(name, dry=False):
    """[(path, status)] of writing the skill of an app."""
    d = K.app(name).skill_dir()
    if d is None:
        return []
    p = Path(d) / "SKILL.md"
    now = state(name)
    if now == "current":
        return [(str(p), "skill up to date")]
    if dry:
        return [(str(p), f"skill: would write ({now})")]
    text = text_for(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if now == "edited":
        (p.parent / "SKILL.md.new").write_text(text, encoding="utf-8", newline="\n")
        return [(str(p), "skill edited by hand: kept; the new one is SKILL.md.new beside it")]
    p.write_text(text, encoding="utf-8", newline="\n")
    return [(str(p), "skill written" if now == "missing" else "skill updated")]


def remove(name):
    d = K.app(name).skill_dir()
    if d is None:
        return []
    p = Path(d) / "SKILL.md"
    now = state(name)
    if now == "missing":
        return []
    if now == "edited":
        return [(str(p), "skill edited by hand: kept")]
    p.unlink()
    for extra in (p.parent / "SKILL.md.new",):
        if extra.exists():
            extra.unlink()
    if not any(p.parent.iterdir()):
        p.parent.rmdir()
    return [(str(p), "skill taken out")]
