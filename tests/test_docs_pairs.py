# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every document for people has a Russian twin name.ru.md (the author, 2026-10-28) that cannot drift from it: a line
to switch the language at the top of both, the same headings by level and order, the same code blocks, the same
links (a link to a document that has a twin leads to the twin in the Russian one) and the same versions."""

import os, re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = [
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "INSTALL_FOR_AI.md",
    "docs/INTAKE.md",
    "docs/SEARCH.md",
    "docs/PACKAGES.md",
    "docs/GLOSSARY.md",
    "docs/CLIENTS.md",
]
FENCE = re.compile(r"^```.*?^```", re.M | re.S)
LINK = re.compile(r"\]\(([^)\s]+)\)")
VERSION = re.compile(r"(?<![\d,.])\d+\.\d+\.\d+(?![\d.])")  # 0.5.4; a decimal "0.5 s" may be "0,5 с" in Russian
HEAD_VERSION = re.compile(r"^#{1,6} v?(\d+\.\d+(?:\.\d+)?)(?![\d.])", re.M)  # a heading that is a version: "## 0.5 — …"


def versions(text):
    text = FENCE.sub("", text)
    return sorted(set(VERSION.findall(text)) | set(HEAD_VERSION.findall(text)))


def twin(path):
    return path[:-3] + ".ru.md"


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def body(text):
    return text.split("\n", 2)[2] if text.count("\n") >= 2 else ""


def headings(text):
    return [len(m) for m in re.findall(r"^(#{1,6}) ", FENCE.sub("", text), re.M)]


def links(text, russian):
    out = []
    names = {os.path.basename(d) for d in DOCS}
    for target in LINK.findall(FENCE.sub("", text)):
        path, _, anchor = target.partition("#")
        if not russian and os.path.basename(path) in names:
            path = twin(path)
        out.append(path if not anchor or path else "#")  # an anchor in the same document is translated with it
    return out


@pytest.mark.parametrize("doc", DOCS)
def test_the_russian_twin_holds_to_the_english_document(doc):
    en, ru = read(doc), read(twin(doc))
    name = os.path.basename(doc)
    assert en.splitlines()[0] == f"English | [Русский]({twin(name)})", "the switch line of the English document"
    assert ru.splitlines()[0] == f"[English]({name}) | Русский", "the switch line of the Russian document"
    en, ru = body(en), body(ru)
    assert headings(ru) == headings(en), "the headings by level and order"
    assert FENCE.findall(ru) == FENCE.findall(en), "the code blocks"
    assert links(ru, True) == links(en, False), "the links"
    assert versions(ru) == versions(en), "the versions named"


@pytest.mark.parametrize("doc", DOCS + [twin(d) for d in DOCS])
def test_a_document_has_no_lone_carriage_return(doc):
    # a "\r" of a Windows path once became a carriage return (inbox\_to_delete\removed_…): text mode reads it as a new line
    with open(os.path.join(ROOT, doc), "rb") as f:
        assert re.search(rb"\r(?!\n)", f.read()) is None
