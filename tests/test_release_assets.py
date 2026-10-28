# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The release carries the source archive of the tagged commit beside the wheel, both in SHA256SUMS.txt, and the
instructions for agents check the archive against it before installing (audit item X3: the agents installed from
the archive GitHub makes, checked by nothing)."""

import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_release_attaches_the_source_archive_and_its_sha256():
    wf = open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8").read()
    assert re.search(r'git archive --format=zip .*-o "dist/assistant_x-\$VERSION-src\.zip" "\$GITHUB_SHA"', wf)
    assert "sha256sum *.whl *-src.zip > SHA256SUMS.txt" in wf and "./*-src.zip SHA256SUMS.txt" in wf


def test_the_instructions_check_the_archive_before_installing():
    text = open(os.path.join(ROOT, "INSTALL_FOR_AI.md"), encoding="utf-8").read()
    step = text.split("## 3. The latest release", 1)[1].split("## 4.", 1)[0]
    assert "assistant_x-<version>-src.zip" in step and "SHA256SUMS.txt" in step and "stop and" in step
    assert step.index("SHA-256") < step.index("Extract it")
