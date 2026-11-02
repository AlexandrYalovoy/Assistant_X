# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hierarchy of the documents (core/hierarchy.py): the default of the general profile, the profile's own, the
user's own hierarchy.json in the workspace over both; a document placed by its designation, else its shelf."""

import json

from assistant_x.core import config, hierarchy as H


def test_the_profile_places_the_documents_by_their_designation():
    h = H.load(None, config.profile_dir("oil-gas-ru"))
    assert h.source.endswith("oil-gas-ru\\hierarchy.json") or h.source.endswith("oil-gas-ru/hierarchy.json")
    assert h.rank("GOST R 58367-2019 / ГОСТ Р 58367-2019", code="N-00001") == 5
    assert h.rank("ТТР-01.02.04-13", code="N-00390") == 5.5  # the company: with the national standards, after them
    assert h.rank("СП 231.1311500.2015", code="N-00357") == 6
    assert h.rank("РД 39-135-94", code="N-00763") == 7
    assert h.rank("СТО 00220256-005-2005", code="N-00580") == 8
    assert h.rank("Федеральный закон от 21.07.1997 N 116-ФЗ", code="R-00001") == 2
    assert h.rank("", "Справочник инженера-нефтяника", code="L-00013") == 10  # a book: by its shelf
    assert h.rank("", "Без обозначения", code="N-09999") == H.UNPLACED
    assert [r for r, _ in h.table("ru")][:2] == [1, 2] and h.name(5, "ru") == "ГОСТ и ГОСТ Р"


def test_the_default_has_no_country_and_the_user_hierarchy_wins(tmp_path):
    h = H.load(tmp_path, tmp_path / "no-profile")
    assert h.source == str(H.DEFAULT) and h.name(1) == "Constitution" and h.rank("ISO 13703", code="N-1") == 4
    own = {"levels": [{"rank": 1, "name": {"en": "Our rules"}, "patterns": ["^OUR-"]}], "shelves": {"L": 3}}
    (tmp_path / H.FILE).write_text(json.dumps(own), encoding="utf-8")
    h = H.load(tmp_path, config.profile_dir("oil-gas-ru"))
    assert h.source == str(tmp_path / H.FILE) and h.rank("OUR-7", code="N-1") == 1 and h.rank("", "x", "L-1") == 3
    assert h.rank("ГОСТ 1510-84", code="N-2") == H.UNPLACED  # the user's hierarchy replaces the profile's


def test_a_bad_hierarchy_is_refused_and_a_broken_file_falls_back(tmp_path):
    assert H.check({"levels": []}) and H.check({"levels": [{"name": "x"}]})
    assert "level 1" in H.check({"levels": [{"rank": 1, "patterns": ["("]}]})
    assert H.check({"levels": [{"rank": 1, "patterns": ["^A"]}]}) == ""
    (tmp_path / H.FILE).write_text("{not json", encoding="utf-8")
    assert H.load(tmp_path, config.profile_dir("oil-gas-ru")).source.endswith("hierarchy.json")
    assert H.load(tmp_path, config.profile_dir("oil-gas-ru")).source != str(tmp_path / H.FILE)
