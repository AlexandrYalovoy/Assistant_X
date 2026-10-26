# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shelves of every library (schemas/shelves.json) and the card languages (core/config.py): the same in every
profile, every genre of the schema on exactly one shelf, the names found in English and Russian; a profile holds only
the knowledge of its field."""

import pytest

from assistant_x.core import card, config

PROFILES = config.profiles()


def test_profiles_are_there():
    assert {"general", "oil-gas-ru"} <= set(PROFILES)


def test_shelves():
    shelves = config.sections()
    letters = [s["letter"] for s in shelves]
    assert letters == ["N", "L", "P", "E", "R", "J", "X"]
    assert len({s["folder"] for s in shelves}) == len(shelves)
    for s in shelves:
        assert s["about"] and {"en", "ru"} <= set(s["name"]) and s["doc_types"]
    placed = [t for s in shelves for t in s["doc_types"]]
    assert sorted(placed) == sorted(card.doc_types()), "every genre on exactly one shelf"
    assert "serial_issue" in config.section("J")["doc_types"] and "other" in config.section("X")["doc_types"]


@pytest.mark.parametrize("name", PROFILES)
def test_a_profile_holds_only_its_field(name):
    """No shelves and no card languages in a profile: the structure of the library is one for everybody."""
    info = config.profile_info({"profile": name})
    assert "sections" not in info and "card_languages" not in info and info["skill"]
    assert config.sections({"profile": name}) == config.sections()


def test_names_and_letters():
    assert config.section_letter("Standards") == "N" and config.section_letter("стандарты") == "N"
    assert config.section_letter("n") == "N" and config.section_letter("04_Datasheets") == "E"
    assert config.section_letter("Datasheets and catalogs") == "E" and config.section_letter("журналы и статьи") == "J"
    assert config.section_letter("Journals") == "J" and config.section_letter("") is None
    assert config.section_name("R") == "Regulations and law" and config.section_name("J", lang="ru") == "Журналы и статьи"
    assert config.section_name("Q") == "Q"
    assert config.doc_types() == card.doc_types()


def test_card_languages_follow_the_document_languages():
    assert config.card_languages({"documents": {"languages": ["ru", "en"]}}) == ["en", "ru"]
    assert config.card_languages({"documents": {"languages": ["en"]}}) == ["en"]
    assert config.card_languages({"documents": {"languages": ["ru"]}}) == ["en", "ru"]  # English always
    assert config.card_languages({"profile": "general"}) == ["en", "ru"]  # the workspace: every pack by default


def test_the_programs_of_a_field_are_its_profile_data():
    """The generic code knows only the generic program files; the engineering programs of oil and gas (HYSYS, PIPESIM…)
    are data of the profile oil-gas-ru; the skill rendered for the general profile has no word of that field."""
    import json
    from pathlib import Path
    from assistant_x.intake import config as intake_cfg
    from assistant_x.setup import skill

    assert set(intake_cfg.PROGRAM_EXT) == {"exe", "dll", "msi"}
    root = Path(intake_cfg.__file__).resolve().parent.parent / "profiles"
    assert "hsc" in json.loads((root / "oil-gas-ru" / "documents.json").read_text(encoding="utf-8"))["program_ext"]
    text = skill.render("general")
    assert not any(w in text for w in ("ГОСТ 1510", "РВС", "резервуар", "Hydrocarbon", "gas_dehydration"))
