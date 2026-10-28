# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Codex keeps the tools of an MCP server behind its search of tools: a small model looked for the library among the
resources of the server and never reached library_guide (the live test of 0.5.1). The instructions of the server and
the skill say where to look."""

from assistant_x.server import texts
from assistant_x.setup import skill


def test_the_instructions_and_the_skill_say_how_to_find_hidden_tools():
    for text in (texts.INSTRUCTIONS, skill.render("general", "agent"), skill.render("general", "claude")):
        assert "search of tools" in text and "library_guide search_library" in text and "no resources" in text
