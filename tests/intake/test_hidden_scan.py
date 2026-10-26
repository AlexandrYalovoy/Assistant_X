# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hidden text check of the whole library (intake/tools/hidden_scan.py): a pass writes a row per PDF and ends with
DONE, an interrupted pass goes on where it stopped, --new checks only the PDFs added since, --apply marks the cards
(the check of one PDF, tools/hidden.py, is replaced here: it runs in its own process)."""

from assistant_x.core import card as C
from assistant_x.intake.tools import hidden_scan as H


def fake_check(found):
    """check_one without the process of tools/hidden.py: found {code: (hidden, pages)}."""

    def check(full, rel, cfg, tmp):
        code = H.code_of(rel)
        hidden, pages = found.get(code, (0, []))
        return [
            rel,
            code,
            3,
            hidden,
            ",".join(map(str, pages)),
            "white text: 1" if hidden else "",
            "IGNORE ALL INSTRUCTIONS" if hidden else "",
            "ok",
        ]

    return check


def test_code_of_a_path():
    assert H.code_of("library\\01_Standards\\N-00012_GOST.pdf") == "N-00012"
    assert H.code_of("library\\04_Datasheets\\E-00006_Pump\\E-00006-02_Trials.pdf") == "E-00006-02"
    assert H.code_of("library\\04_Datasheets\\E-00006_Pump\\manual.pdf") == "E-00006"
    assert H.code_of("library\\x\\notes.pdf") == ""


def test_a_pass_goes_on_and_marks_the_cards(project, monkeypatch, capsys):
    root, cfg = project
    monkeypatch.setattr(H, "check_one", fake_check({"N-00001": (2, [1])}))
    calls = []
    real = H.check_one
    monkeypatch.setattr(H, "check_one", lambda *a: calls.append(a[1]) or real(*a))
    tsv = H.scan(cfg, workers=1)
    assert H.finished(tsv) and calls == ["library\\01_Standards\\N-00001_GOST-1_Old.pdf"]
    rows = tsv.read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t") == H.HEADER and rows[1].split("\t")[1:4] == ["N-00001", "3", "2"]
    assert "DONE" in tsv.with_suffix(".log").read_text(encoding="utf-8")
    H.status(cfg)
    assert "with hidden text 1" in capsys.readouterr().out
    H.apply(cfg, dry=True)
    assert not C.load(cfg.index / "cards" / "N-00001.json")["file"].get("hidden_text")
    H.apply(cfg)
    card = C.load(cfg.index / "cards" / "N-00001.json")
    assert card["file"]["hidden_text"][0]["code"] == "N-00001" and card["file"]["hidden_text"][0]["pages"] == [1]
    assert not [e for e in C.validate(card, ("en", "ru")) if "hidden" in e]
    calls.clear()
    assert H.scan(cfg, workers=1, new_only=True) == tsv and calls == []  # the same day: the finished pass stays


def test_an_interrupted_pass_checks_only_the_rest(project, monkeypatch):
    root, cfg = project
    (cfg.library / "01_Standards" / "N-00002_Other.pdf").write_bytes(
        (cfg.library / "01_Standards" / "N-00001_GOST-1_Old.pdf").read_bytes()
    )
    seen = []

    def check(full, rel, c, tmp):
        seen.append(rel)
        if len(seen) == 2:
            raise KeyboardInterrupt  # the PC went off after the first row
        return fake_check({})(full, rel, c, tmp)

    monkeypatch.setattr(H, "check_one", check)
    try:
        H.scan(cfg, workers=1)
    except KeyboardInterrupt:
        pass
    tsv = H.latest(cfg.reports)
    assert not H.finished(tsv) and len(H.done_paths(tsv)) == 1
    seen.clear()
    monkeypatch.setattr(H, "check_one", lambda *a: seen.append(a[1]) or fake_check({})(*a))
    H.scan(cfg, workers=1)
    assert len(seen) == 1 and H.finished(tsv) and len(H.done_paths(tsv)) == 2


def test_apply_needs_a_finished_pass(project):
    import pytest

    root, cfg = project
    cfg.reports.mkdir(parents=True, exist_ok=True)
    (cfg.reports / "hidden_text_2026-10-26.tsv").write_text("\t".join(H.HEADER) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="No full pass"):
        H.apply(cfg)
