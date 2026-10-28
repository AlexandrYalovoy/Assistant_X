# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every language rule comes from the language packs and the words of a field from its profile: a third pack (a tiny
German one, tests/lang/de, through AX_LANG_DIRS) works without a line of code, and the general profile has none of
the oil and gas words the profile oil-gas-ru adds."""

import json, os, subprocess, sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
GERMAN = (
    "Die Anlage ist für den Betrieb mit Erdgas ausgelegt und der Druck darf nicht über den Grenzwert steigen. "
    "Die Prüfung der Behälter erfolgt mit Wasser, die Größe der Öffnungen ist zu prüfen. "
) * 4
ENGLISH = (
    "The separator is designed for the operation with natural gas and the pressure shall not exceed the limit. "
    "The vessels are tested with water, and the size of the openings is checked. "
) * 4
RUSSIAN = (
    "Сепаратор предназначен для работы на природном газе, давление не должно превышать предельное значение. "
    "Сосуды испытывают водой, размеры отверстий проверяют. "
) * 4

PROBE = r"""
import json, sys
from assistant_x.core import common, lang
from assistant_x.intake import metadraft
from assistant_x.intake.tools import dupcheck, ocr_score
texts = json.loads(sys.stdin.read())
out = {
    "active": lang.active(), "tesseract": lang.tesseract(), "available": lang.available(),
    "langs": {k: common.text_stats([(1, t)])["lang"] for k, t in texts.items()},
    "shares": {k: {c: round(s, 2) for c, s in common.letter_shares(t).items()} for k, t in texts.items()},
    "text_lang": metadraft.text_lang("=== page 1 ===\n\n" + texts["de"][:300]),
    "dup_words": dupcheck.words("Größe der Öffnungen"),
    "kinds": [ocr_score.kind(t) for t in ("Größe", "Grоße", "zu", "Test", "Тест")],
    "two": [ocr_score.two_known(t) for t in ("zu", "of", "xq")],
    "score": ocr_score.word_counts(texts["de"])[1],
    "stem": ocr_score.stem("größe"),
}
print(json.dumps(out, ensure_ascii=False))
"""


def run_probe(tmp_path, languages, profile="general", texts=None):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    langs = ", ".join(f'"{c}"' for c in languages)
    (ws / "assistant_x.toml").write_text(f'profile = "{profile}"\n[documents]\nlanguages = [{langs}]\n', encoding="utf-8")
    env = {**os.environ, "AX_WORKSPACE": str(ws), "AX_LANG_DIRS": str(TESTS / "lang"), "PYTHONUTF8": "1"}
    p = subprocess.run(
        [sys.executable, "-c", PROBE],
        input=json.dumps(texts or {}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=300,
        cwd=str(TESTS.parent),
    )
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.splitlines()[-1])


@pytest.fixture(scope="module")
def three(tmp_path_factory):
    texts = {"de": GERMAN, "en": ENGLISH, "ru": RUSSIAN, "ru+de": RUSSIAN + GERMAN}
    return run_probe(tmp_path_factory.mktemp("three"), ["ru", "en", "de"], texts=texts)


def test_a_third_pack_is_data_only(three):
    assert three["active"] == ["ru", "en", "de"] and "de" in three["available"]
    assert three["tesseract"] == "rus+eng+deu"


def test_languages_of_a_text_by_three_packs(three):
    # English and German share their letters: the stop words of the packs tell them apart
    assert three["langs"] == {"de": "de", "en": "en", "ru": "ru", "ru+de": "ru+de"}
    assert three["shares"]["de"]["de"] == 1.0 and three["shares"]["de"]["en"] < 1.0 and three["shares"]["ru"]["ru"] == 1.0
    assert three["text_lang"] == ["de"]


def test_regexes_take_the_letters_of_every_pack(three):
    assert three["dup_words"] == ["größe", "der", "öffnungen"]
    # a German word is a word, a Cyrillic o inside it mixes scripts; a two-letter word of either pack of the alphabet
    assert three["kinds"] == ["word", "mixed", "en2", "word", "word"]
    assert three["two"] == [True, True, False]
    assert three["score"] == 0  # no German word is taken for garbage
    assert three["stem"] == "gross"  # the German stemmer: the word has letters only German has


def test_industry_words_are_in_the_profile_only(tmp_path):
    import importlib

    code = r"""
import json
from assistant_x.core import lang
from assistant_x.intake import metadraft
print(json.dumps({"api": metadraft.designation("API RP 14C Analysis"), "gost": metadraft.designation("ГОСТ Р 51858-2002"),
                  "shell": metadraft.publisher_of("Shell Global Solutions"), "en": metadraft.en_title("Насосы. Общие требования"),
                  "types": metadraft.TYPE_ORDER}, ensure_ascii=False))
"""
    out = {}
    for profile in ("general", "oil-gas-ru"):
        ws = tmp_path / profile
        ws.mkdir()
        (ws / "assistant_x.toml").write_text(f'profile = "{profile}"\n', encoding="utf-8")
        p = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "AX_WORKSPACE": str(ws), "PYTHONUTF8": "1"},
            timeout=300,
            cwd=str(TESTS.parent),
        )
        assert p.returncode == 0, p.stderr[-2000:]
        out[profile] = json.loads(p.stdout.splitlines()[-1])
    assert out["oil-gas-ru"]["api"] == "API RP 14C" and out["general"]["api"] is None
    assert out["oil-gas-ru"]["shell"] == "Shell" and out["general"]["shell"] == ""
    assert out["oil-gas-ru"]["en"] == "Pumps-General-Requirements" and out["general"]["en"] == ""
    assert out["general"]["gost"] == out["oil-gas-ru"]["gost"] == "ГОСТ Р 51858-2002"  # state standards: the packs
    card = importlib.import_module("assistant_x.core.card")
    assert out["general"]["types"] == [t for t in card.doc_types() if t not in ("other", "book")] + ["book"]  # a book last


@pytest.mark.parametrize(
    "text, doc_type",
    [
        ("ФЕДЕРАЛЬНЫЙ ЗАКОН О промышленной безопасности", "law"),
        ("Клинические рекомендации. Артериальная гипертензия у взрослых", "clinical_guideline"),
        ("ДОГОВОР № 15/2026 на выполнение работ", "contract"),
        ("Диссертация на соискание учёной степени кандидата технических наук", "thesis"),
        ("Протокол испытаний № 7 образцов труб", "report"),
        ("Инструкция по монтажу и наладке", "manual"),
        ("Презентация проекта", "presentation"),
        ("Курс лекций по гидравлике", "lecture_notes"),
        ("Сборник трудов конференции", "proceedings"),
        ("A thesis submitted in partial fulfillment of the requirements", "thesis"),
        ("Proceedings of the 12th symposium", "proceedings"),
        ("Keywords: corrosion, pipelines", "article"),
        ("Clinical practice guidelines for asthma", "clinical_guideline"),
        ("Operation and maintenance manual", "datasheet"),
        ("Руководство по эксплуатации", "datasheet"),
    ],
)
def test_every_genre_has_words(text, doc_type):
    from assistant_x.intake import metadraft

    assert metadraft.doc_type_of(text, None) == doc_type


def test_doc_type_words_for_every_genre():
    from assistant_x.core import card, lang

    for code in ("ru", "en"):
        words = lang.get(code, "doc_type_words")
        assert set(card.doc_types()) - {"other"} <= set(words), code


def test_every_pack_has_every_key():
    """The packs of the program carry the same keys (a key whose words a language has none of is there, empty, and
    its _comment says why): a key missing from one pack silently turns a feature off for its documents."""
    from assistant_x.core import lang

    root = Path(lang.__file__).resolve().parent.parent / "lang"
    packs = {d.name: {k for k in lang.pack(d.name) if not k.startswith("_")} for d in root.iterdir() if d.is_dir()}
    every = set().union(*packs.values())
    assert {code: sorted(every - keys) for code, keys in packs.items()} == {code: [] for code in packs}


ENGLISH_PROBE = r"""
import json
from assistant_x.core import textmap
from assistant_x.intake import metadraft, prepare
from assistant_x.search import bookmap
caption = {k: [bool(rx.search(x)) for x in ("Table 4.2 Pressure drop", "Figure 3. Separator", "Appendix B", "Annex 2",
                                            "The table shows")] for k, rx in textmap.DEF_RX.items() if k in "tra"}
text = "See Table 4.2 and Fig. 3, equation (5) in Section 5.3 and Chapter 2, Annex 3."
print(json.dumps({
    "caption": caption,
    "refs": [(m.group("k"), m.group(2), bookmap.ref_kind(m.group("k"))) for m in bookmap.REF_RX.finditer(text)],
    "generic": [bool(textmap.GENERIC_RX.match(x)) for x in ("Table 3", "Contents", "Foreword", "Separator design")],
    "toc_heading": bool(textmap.TOC_HEADING_RX.search("# Table of Contents")),
    "toc_skip": [bool(textmap.TOC_SKIP_RX.search(x)) for x in ("List of tables", "Figure 4 Layout", "Introduction")],
    "supersedes": (lambda m: next(g for g in m.groups() if g) if m else None)(
        metadraft.SUPERSEDES.search("This edition replaces ISO 1234:2010. It is a revision")),
    "standard": not metadraft.NOT_STANDARDS.match("ISO 1234"),
    "personal": [prepare.personal({}, x) for x in ("Home/tax return 2025.pdf", "Scans/passport scan.jpg",
                                                   "Standards/ISO 1234.pdf", "Pumps/passport of pump P-101.pdf")],
    "publisher": metadraft.publisher_of("Published by Gulf Publishing, Houston, 2019"),
    "stamp": bool(metadraft.STAMP.search("SCALE 1:50  SHEET 2 OF 4  DRAWN BY J. Smith")),
}))
"""


def test_english_recognition(tmp_path):
    """An English-only workspace: captions, references, generic and contents headings, the edition a standard
    replaces, personal papers, publishers and title blocks come from the English pack (they did not before)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "assistant_x.toml").write_text('profile = "general"\n[documents]\nlanguages = ["en"]\n', encoding="utf-8")
    p = subprocess.run(
        [sys.executable, "-c", ENGLISH_PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "AX_WORKSPACE": str(ws), "PYTHONUTF8": "1"},
        timeout=300,
        cwd=str(TESTS.parent),
    )
    assert p.returncode == 0, p.stderr[-2000:]
    out = json.loads(p.stdout.splitlines()[-1])
    assert out["caption"] == {
        "t": [True, False, False, False, False],
        "r": [False, True, False, False, False],
        "a": [False, False, True, True, False],
    }
    assert out["refs"] == [
        ["Table", "4.2", "t"],
        ["Fig.", "3", "r"],
        ["equation", "5", "f"],
        ["Section", "5.3", "s"],
        ["Chapter", "2", "c"],
        ["Annex", "3", "a"],
    ]
    assert out["generic"] == [True, True, True, False] and out["toc_heading"]
    assert out["toc_skip"] == [True, True, False]
    assert out["supersedes"] == "ISO 1234:2010" and out["standard"]
    assert out["personal"][:2] == ["tax return", "passport scan"] and out["personal"][2:] == [None, None]
    assert "Gulf Publishing" in out["publisher"] and out["stamp"]
