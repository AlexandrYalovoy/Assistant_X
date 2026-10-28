# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The documents made from the code (assistant-x gen-docs) are the ones committed: a new tool, command, app or version
without `assistant-x gen-docs` fails here (and in CI). The plugin files are valid JSON with the version of the code."""

import json

from assistant_x import __version__
from assistant_x.setup import gen_docs


def test_the_committed_documents_are_made_by_gen_docs():
    stale = [
        str(p.relative_to(gen_docs.ROOT))
        for p, text in gen_docs.targets().items()
        if not p.exists() or p.read_text(encoding="utf-8") != text
    ]
    assert not stale, f"run assistant-x gen-docs: {stale}"


def test_the_plugin_and_the_marketplaces():
    root = gen_docs.ROOT
    portable = json.loads((root / "plugins" / "assistant-x" / "plugin.json").read_text(encoding="utf-8"))
    claude = json.loads((root / "plugins" / "assistant-x" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert portable["version"] == claude["version"] == __version__ and portable["name"] == claude["name"] == "assistant-x"
    onboarding = portable["extensions"]["com.openai"]["onboardingSkill"]
    assert onboarding.startswith("./") and (root / "plugins" / "assistant-x" / onboarding[2:]).is_file()
    for m in (root / ".claude-plugin" / "marketplace.json", root / ".agents" / "plugins" / "marketplace.json"):
        market = json.loads(m.read_text(encoding="utf-8"))
        [entry] = market["plugins"]
        src = entry["source"] if isinstance(entry["source"], str) else entry["source"]["path"]
        assert src == "./plugins/assistant-x"
    codex = json.loads((root / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))["plugins"][0]
    assert {"installation", "authentication"} <= set(codex["policy"]) and codex["category"]


def test_the_agent_instructions_point_at_the_latest_release():
    text = (gen_docs.ROOT / "INSTALL_FOR_AI.md").read_text(encoding="utf-8")
    assert "/releases/latest" in text and "--yes --json" in text and "connect --check" in text
    assert "`library_guide`" in text and f"version {__version__}" in text
    agents = (gen_docs.ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count(gen_docs.BEGIN) == 1 and "INSTALL_FOR_AI.md" in agents
