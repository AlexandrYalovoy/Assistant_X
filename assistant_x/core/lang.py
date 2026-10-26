# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Language packs: what the code needs to know about the language of the documents, as data.

    assistant_x/lang/<code>/*.json      one pack per language (ru, en); the keys of all its files form one table

A pack holds the letters of the language (for character classes), the case folding, the stemmer and stop words, and
the words and patterns that match documents written in it: headings, references to tables and figures, designations
of standards, boilerplate, title pages, personal papers, hidden instructions. The Python code holds no words of a
document language; it composes its patterns from the packs of the document languages in use. Every pack of the
program has every key (tests/test_lang_packs.py): a key whose words a language has none of is there, empty, and the
_comment of its file says why; an empty alternation never matches (alt).

    [documents] languages = ["ru", "en"]   in assistant_x.toml (the default: every pack, Russian first)
    AX_LANG_DIRS                           more folders of packs (a pack of your own), separated as in PATH

The words of a field of work (the designations of its standards, its publishers, the words of its titles) are in the
domain profile, profiles/<name>/documents.json: words(), alt(), table() and lists() add them after the packs. Which
letters, stemmer, stop words and thresholds belong to a language is in its pack only (letters(), langs_of() in
core/common.py): the code holds no rule for one language in particular.
"""

import functools, json, os, re
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parent.parent / "lang"
DEFAULT = ("ru", "en")
PROFILE_WORDS = "documents.json"  # the words of a domain profile, in profiles/<name>/


def pack_dirs():
    """The folders of the packs: those of the package, then the ones of AX_LANG_DIRS."""
    extra = [Path(p) for p in (os.environ.get("AX_LANG_DIRS") or "").split(os.pathsep) if p]
    return [LANG_DIR, *extra]


@functools.lru_cache(maxsize=None)
def pack(code):
    """All the data of one language: the keys of every JSON file of lang/<code>/ (a key may appear once)."""
    out = {}
    d = next((x / code for x in pack_dirs() if (x / code).is_dir()), None)
    if d is None:
        raise ValueError(f"No language pack {code!r} (packs: {', '.join(available())})")
    for p in sorted(d.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for k, v in data.items():
            if k.startswith("_"):
                continue
            if k in out:
                raise ValueError(f"{p}: the key {k!r} is in another file of the pack {code!r} already")
            out[k] = v
    return out


@functools.lru_cache(maxsize=None)
def vocab(code):
    """The seed vocabulary of a pack (lang/<code>/vocab.txt: a word form a line, "#" comments): the recognition score
    knows these words under the vocabulary of the library; empty when the pack has none."""
    d = next((x / code for x in pack_dirs() if (x / code).is_dir()), None)
    p = d / "vocab.txt" if d else None
    if not p or not p.is_file():
        return frozenset()
    return frozenset(w for w in (ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()) if w and w[0] != "#")


def available():
    return sorted(
        {p.name for d in pack_dirs() if d.is_dir() for p in d.iterdir() if p.is_dir() and not p.name.startswith("_")}
    )


@functools.lru_cache(maxsize=None)
def active():
    """The document languages of the workspace, in order ([documents] languages of assistant_x.toml)."""
    from assistant_x.core import config

    given = (config.load()[1].get("documents") or {}).get("languages")
    langs = tuple(given) if given else DEFAULT
    for code in langs:
        pack(code)
    return langs


def get(code, key, default=None):
    return pack(code).get(key, default)


@functools.lru_cache(maxsize=None)
def profile_words():
    """The words of the domain profile in use (profiles/<name>/documents.json; {} for a profile without them)."""
    from assistant_x.core import config

    p = config.profile_dir(config.load()[1].get("profile")) / PROFILE_WORDS
    if not p.is_file():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def words(key):
    """The list under key of every active language, in the order of the languages, then the one of the profile."""
    out = []
    for code in active():
        out += pack(code).get(key, [])
    return out + list(profile_words().get(key, []))


def alt(key, escape=False):
    """The words under key as a regex alternation ("a|b|c"); "(?!)", which never matches, when no active pack has
    any (an empty alternation would match everywhere)."""
    return ("|".join(re.escape(w) for w in words(key)) if escape else "|".join(words(key))) or "(?!)"


def chars(key):
    """A character-class piece (e.g. the lower-case letters) of every active language joined (Russian, then Latin)."""
    return "".join(pack(code).get(key, "") for code in active())


def table(key):
    """The dict under key of every active language merged, then the one of the profile (a later one does not override
    an earlier one)."""
    out = {}
    for d in [pack(code).get(key, {}) for code in active()] + [profile_words().get(key, {})]:
        for k, v in d.items():
            out.setdefault(k, v)
    return out


def lists(key):
    """The dict of lists under key ({"book": [words], …}) of every active language and the profile, the lists joined."""
    out = {}
    for d in [pack(code).get(key, {}) for code in active()] + [profile_words().get(key, {})]:
        for k, v in d.items():
            out.setdefault(k, []).extend(v)
    return out


def letters(key="letters"):
    """{code: character-class piece} of every active language that has key (its letters by default), in order."""
    return {code: pack(code)[key] for code in active() if pack(code).get(key)}


@functools.lru_cache(maxsize=None)
def _homoglyph_map():
    return str.maketrans(table("homoglyphs"))


def homoglyphs(text):
    """Lower-case letters of two scripts that look alike as one (the "homoglyphs" table: a Cyrillic letter as the
    Latin one it looks like), for the exact index and the comparison of quotes: an OCR Latin x in a Cyrillic word."""
    return text.translate(_homoglyph_map())


def fold(text):
    """Case-insensitive comparison form of the letters of the active languages (the "fold" table: Russian yo as ye)."""
    for a, b in table("fold").items():
        text = text.replace(a, b)
    return text


def tesseract():
    """The languages of Tesseract for the document languages in use ("rus+eng"): the "tesseract" codes of the packs."""
    return "+".join(dict.fromkeys(words("tesseract"))) or "eng"
