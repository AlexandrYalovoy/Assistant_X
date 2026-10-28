# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recognition score (tools/ocr_score.py), the OCR of a page with word confidence (tools/ocr_page.py), the commands
around them (ocr_quality.py, ocr_redo.py). The fast tests need no Tesseract; the slow ones recognise turned pages and
a scan for real (python -m pytest -m slow intake/tests)."""

import datetime, json, os

import pytest

from assistant_x.intake import config as intake_cfg
from assistant_x.intake.tools import ocr_page
from assistant_x.intake.tools import ocr_score
from assistant_x.intake import quality_report

CLEAN = (
    "Сепаратор нефтегазовый предназначен для отделения газа от нефти на объектах сбора и подготовки нефти. "  # Russian text
    "Скорость газа в сечении аппарата не должна превышать допустимую, рассчитанную по плотности газа и нефти "
    "при рабочем давлении и температуре. Трубопровод рассчитывают на прочность по ГОСТ 32569-2013 при "
    "давлении 4,0 МПа и температуре 120 °С."
)
GARBAGE = (
    "ее ае Ws oe ры ое 'Ч Ва} ЕНЕНЕa pacтвор ХХ ХХ |||] —| Иzyомоеca eenpcuameanas Wl iW ee ae "
    "a и е р ы й т н о г ь в ‹ а е ы ‚ — =: ap sa ts"
)


@pytest.fixture(scope="module")
def vocab(tmp_path_factory):
    """A vocabulary built from four small texts (parts of one document count once)."""
    d = tmp_path_factory.mktemp("texts")
    for code in ("N-00001", "N-00002", "L-00001", "E-00001"):
        (d / f"{code}.md").write_text(f"=== page 1 ===\n\n{CLEAN}\n", encoding="utf-8")
    (d / "N-00001-02.md").write_text("=== page 1 ===\n\nредкоеслово\n", encoding="utf-8")
    (d / "N-00001-03.md").write_text("=== page 1 ===\n\nредкоеслово\n", encoding="utf-8")
    (d / "N-00001-04.md").write_text("=== page 1 ===\n\nредкоеслово\n", encoding="utf-8")
    out = str(d / "vocab.txt")
    words, stems, docs = ocr_score.build_vocab(str(d), out)
    assert docs == 4 and words > 20
    return ocr_score.load_vocab(out)


def test_vocabulary_counts_documents_not_parts(vocab):
    words, _ = vocab
    assert "сепаратор" in words and "нефти" in words
    assert "редкоеслово" not in words  # three parts of one document are one document


def test_kinds_of_tokens():
    assert ocr_score.kind("10704-91") == ocr_score.kind("М100") == "num"
    assert ocr_score.kind("pacтвор") == "mixed"  # Latin p, a, c among Cyrillic letters
    assert ocr_score.kind("AARAAA") == "junk" and ocr_score.kind("ХХ") == "junk" and ocr_score.kind("II") == "abbr"
    assert ocr_score.kind("ГОСТ") == "word" and ocr_score.kind("НД") == "abbr"
    assert ocr_score.kind("ры") == "ru2" and ocr_score.kind("iW") == "en2"
    assert ocr_score.kind("Δp") == "other"
    assert ocr_score.kind("ƿǠǘǛ") == "broken" and ocr_score.kind("��лист") == "broken"


def test_clean_text_scores_high_and_garbage_low(vocab):
    n, bad, _ = ocr_score.word_counts(CLEAN, vocab)
    assert ocr_score.page_score(n, bad) >= 95
    n, bad, ex = ocr_score.word_counts(GARBAGE, vocab)
    assert ocr_score.page_score(n, bad) < 50 and "pacтвор" in ex
    # a word broken at the line end (also inside picture text) is one word
    assert ocr_score.word_counts("сепара-\nтор", vocab)[1] == ocr_score.word_counts("сепара-<br>тор", vocab)[1] == 0


def test_score_formula():
    q = ocr_score.QUALITY
    assert ocr_score.words_score(q["ocr_words_free"]) == 100
    assert 65 <= ocr_score.words_score(q["ocr_retry_nonword"]) <= 72  # the retry threshold sits near the note one
    assert ocr_score.page_score(0, 0) is None
    assert ocr_score.page_score(100, 0, 95, 0.0) == 100
    low = ocr_score.page_score(100, 0, 50, 0.6)
    assert low < 100 and low >= 100 * (1 - q["ocr_conf_weight"])  # the words keep their weight
    res = ocr_score.score_text("=== page 1 ===\nа\n=== page 2 ===\n" + CLEAN, {2: {"conf": 90, "low": 0.0, "tokens": 50}})
    assert res["pages"][0]["score"] is None and res["score"] == res["pages"][1]["score"]


def test_tsv_roundtrip_and_search_side(tmp_path, vocab):
    from assistant_x.core import common

    res = ocr_score.score_text(f"=== page 1 ===\n{CLEAN}\n=== page 2 ===\n{GARBAGE}\n", vocab=vocab)
    row = ocr_score.row_of("N-00001", res, "text", "2026-10-23")
    assert row["pages"] == "2" and row["pages_below_threshold"] == "1" and row["worst_pages"].startswith("2:")
    p = tmp_path / ocr_score.TSV_NAME
    ocr_score.write_tsv(p, {"N-00001": row, "L-00001": {**row, "code": "L-00001", "score": "41.0"}})
    assert ocr_score.read_tsv(p)["N-00001"] == row
    scores = common.read_ocr_scores(str(p))
    assert scores["L-00001"] == 41.0
    assert "recognition score 41 of 100" in common.quality_note({"fffd_per_1000": 0, "empty_share": 0}, "", "", 41.0)
    assert common.quality_note({"fffd_per_1000": 0, "empty_share": 0}, "", "", 90.0) == ""


def test_quality_report_flags_a_low_score():
    m = quality_report.measure(f"=== page 1 ===\n{CLEAN}\n", {"ocr_score": 42.0, "ocr_low_pages": 3})
    probs = quality_report.problems(m)
    assert any("recognition score 42" in p[0] and p[2] == "medium" for p in probs)
    assert not quality_report.problems(quality_report.measure(f"=== page 1 ===\n{CLEAN}\n", {"ocr_score": 90.0}))


def test_parse_tsv_and_choose():
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t96.5\tПринцип\n"
        "5\t1\t1\t1\t1\t2\t70\t10\t50\t20\t91.0\tработы\n"
        "5\t1\t1\t1\t2\t1\t10\t40\t50\t20\t-1\t\n"
        "5\t1\t1\t1\t2\t2\t10\t40\t50\t20\t40.0\tдавление\n"
    )
    text, confs, words = ocr_page.parse_tsv(tsv)
    assert text == "Принцип работы\nдавление" and confs == [96.5, 91.0, 40.0] and words[1][:4] == (70, 10, 50, 20)
    v = lambda s: {"m": {"score": s}}  # noqa: E731
    assert ocr_page.choose({"300": v(80), "rotate 90": v(75)}, 90) == "rotate 90"  # turned unless much worse
    assert ocr_page.choose({"300": v(80), "rotate 90": v(60)}, 90) == "300"
    assert ocr_page.choose({"300": v(50), "400": v(62), "b/w": v(40)}, 0) == "400"


def test_words_put_on_the_page_keep_their_gaps():
    """Each recognised word goes on the page by itself: a table cell reads "Принцип работы", not "Принципработы"."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=200, height=100)
    ocr_page.insert_words(page, [(20, 20, 140, 40, "Принцип", "a"), (180, 20, 120, 40, "работы", "a")], 400, 200)
    text = page.get_text().translate(ocr_page.FONT_FIX)
    assert "Принцип работы" in text


def test_lost_words_take_the_plain_text():
    from assistant_x.intake.tools import convert_md

    rec = convert_md.words("Год Наименование заказчика КТК Новатек Роснефть приводы редукторы " * 5)
    assert convert_md.kept(rec, convert_md.words("Референс")) < ocr_page.LOST_SHARE
    assert convert_md.kept(rec, rec) == 1.0


def test_library_pdf_by_the_manifest(project):
    from assistant_x.intake import ocr_redo

    root, cfg = project
    (cfg.index / "manifest.tsv").write_text(
        "path\tsize\tmodified\tsha256\tcode\nlibrary\\01_Standards\\N-00001_GOST-1_Old.pdf\t1\t-\tab\tN-00001\n",
        encoding="utf-8",
    )
    assert ocr_redo.library_pdf(cfg, "N-00001").name == "N-00001_GOST-1_Old.pdf"
    assert ocr_redo.library_pdf(cfg, "N-00002") is None


def tesseract_env(monkeypatch):
    exe = intake_cfg.find_tesseract()
    if not exe:
        pytest.skip("no Tesseract")
    monkeypatch.setenv("TESSERACT", exe)
    data = intake_cfg.find_tessdata(None, exe)
    if data:
        monkeypatch.setenv("TESSDATA_PREFIX", data)
    monkeypatch.setattr(ocr_page, "_tess", None)


def test_tessdata_on_the_command_line(tmp_path, monkeypatch):
    """Tesseract 5.5 fails on a non-ASCII tessdata path from TESSDATA_PREFIX or beside its program: the path goes as
    --tessdata-dir and out of its environment."""
    data = tmp_path / "programs" / "Tesseract-OCR" / "tessdata"
    data.mkdir(parents=True)
    exe = data.parent / "tesseract.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(ocr_page, "_tess", str(exe))
    env = {"TESSDATA_PREFIX": "D:\\Языки", "PATH": "x"}  # a Cyrillic folder name
    assert ocr_page.tessdata_args(env) == ["--tessdata-dir", "D:\\Языки"] and env == {"PATH": "x"}
    assert ocr_page.tessdata_args({}) == ["--tessdata-dir", str(data)]  # no setting: the tessdata beside the program


@pytest.mark.slow
def test_turned_pages_are_read(tmp_path, monkeypatch):
    """A page scanned on its side or upside down is turned by the orientation Tesseract sees and read again."""
    import numpy as np
    import pymupdf
    from tests.intake.intake_fixtures import FONT
    from assistant_x.intake.tools import convert_md

    tesseract_env(monkeypatch)
    src = pymupdf.open()
    page = src.new_page()
    page.insert_textbox(pymupdf.Rect(50, 60, 545, 780), (CLEAN + "\n\n") * 4, fontsize=14, fontname="ru", fontfile=FONT)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, page.get_pixmap(dpi=200))
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, : pix.width]
    doc = pymupdf.open()
    for k in (0, 1, 2):  # upright, turned 90° counter-clockwise, upside down
        r = np.ascontiguousarray(np.rot90(a, k=k))
        img = pymupdf.Pixmap(pymupdf.csGRAY, r.shape[1], r.shape[0], r.tobytes(), 0)
        p = doc.new_page(width=r.shape[1] * 72 / 200, height=r.shape[0] * 72 / 200)
        p.insert_image(p.rect, pixmap=img)
    path = tmp_path / "turned.pdf"
    doc.save(path)
    res, stats = convert_md.markdown(str(path), 0, [0, 1, 2], True)
    assert stats[1]["rotate"] == 0 and stats[2]["rotate"] == 90 and stats[3]["rotate"] == 180
    for n in (1, 2, 3):
        text = res[n].lower()
        assert "сепаратор" in text and "плотности газа" in text, (n, res[n][:200])
        assert stats[n]["conf"] > 70 and stats[n]["score"] > 80, stats[n]


@pytest.mark.slow
def test_redo_replaces_only_a_better_text(project, monkeypatch):
    """K11: a scan whose library text is garbage gets the new text; the second run finds no gain and keeps it."""
    from assistant_x.intake import ocr_redo
    from tests.intake.intake_fixtures import scan_pdf

    tesseract_env(monkeypatch)
    root, cfg = project
    cfg["tesseract"] = os.environ["TESSERACT"]
    lib = cfg.library / "02_Literature"
    lib.mkdir(parents=True)
    scan_pdf(lib / "L-00001_Scan.pdf", "СКАН СТРАНИЦЫ\nДавление насыщения нефти газом\nопределяют по пробам нефти")
    (cfg.index / "manifest.tsv").write_text(
        "путь\tразмер\tизменён\tsha256\tшифр\n"  # an older manifest header
        "library\\02_Literature\\L-00001_Scan.pdf\t1\t-\tab\tL-00001\n",
        encoding="utf-8",
    )
    (cfg.index / "texts" / "L-00001.md").write_text(
        "=== page 1 ===\n\nee ae ры ое oe Иzyомоеca ХХ ХХ |||] eenpcuameanas\n", encoding="utf-8"
    )

    class A:
        codes, worst, below, dry_run = ["L-00001", "L-00009"], None, None, False

    assert ocr_redo.cmd_redo(cfg, A()) == 0
    text = (cfg.index / "texts" / "L-00001.md").read_text(encoding="utf-8").lower()
    assert "давление" in text and "насыщения" in text
    aside = cfg.inbox / "_to_delete" / f"redo_{datetime.date.today().isoformat()}" / "L-00001.md"
    assert "eenpcuameanas" in aside.read_text(encoding="utf-8")  # the replaced text is kept aside
    assert list(cfg.work.glob("redo/*/balance.log"))  # read by the workers and the regulator of the intake
    row = ocr_score.read_tsv(cfg.index / ocr_score.TSV_NAME)["L-00001"]
    assert row["source"] == "redo" and float(row["score"]) > 50
    events = (cfg.index / "intake_events.tsv").read_text(encoding="utf-8")
    assert "recognized again: text replaced" in events and "L-00009" in events  # the missing one is in the journal too
    assert ocr_redo.cmd_redo(cfg, A()) == 0  # again: no gain, the text stays
    assert (cfg.index / "texts" / "L-00001.md").read_text(encoding="utf-8").lower() == text
    assert "text kept" in (cfg.index / "intake_events.tsv").read_text(encoding="utf-8").splitlines()[-2]
    assert json.loads(json.dumps(row))  # the row is plain text


def test_drawing_sheet_rule():
    """1-2 pages bigger than A3 with under 150 words is a drawing; an A4 page or a long document is not."""
    a1 = 1684 * 2384  # A1 in points
    assert ocr_score.is_drawing(1, a1, 40) and ocr_score.is_drawing(2, a1)
    assert not ocr_score.is_drawing(1, 595 * 842, 40)  # A4
    assert not ocr_score.is_drawing(3, a1, 40)  # a set of sheets is a document
    assert not ocr_score.is_drawing(1, a1, 400)  # a big sheet full of text


def test_drawing_has_no_quality_problems():
    from assistant_x.intake import quality_report

    m = {
        "no_ocr_pages": 0,
        "fffd_per_1000": 0,
        "fffd": 0,
        "pages": 1,
        "empty_pages": 1,
        "ocr_share": 1.0,
        "letters": {"ru": 0.5, "en": 0.5},
        "ocr_score": 12,
        "ocr_low_pages": 1,
        "fallback": 0,
    }
    assert quality_report.problems(m)  # a scan like this would go to sources_to_update
    assert quality_report.problems({**m, "drawing": True}) == []


def test_a_replaced_text_is_kept_aside(tmp_path):
    from assistant_x.intake import ocr_redo

    texts, aside = tmp_path / "texts", tmp_path / "inbox" / "_to_delete" / "redo_2026-10-27"
    texts.mkdir()
    (texts / "N-00001.md").write_text("old", encoding="utf-8")
    (texts / "N-00001.pages.json").write_text("{}", encoding="utf-8")
    ocr_redo.keep_aside(texts, "N-00001", aside)
    assert sorted(p.name for p in aside.iterdir()) == ["N-00001.md", "N-00001.pages.json"]
    (texts / "N-00001.md").write_text("newer", encoding="utf-8")
    ocr_redo.keep_aside(texts, "N-00001", aside)  # a second run the same day keeps the first copy
    assert (aside / "N-00001.md").read_text(encoding="utf-8") == "old" and len(list(aside.glob("*_N-00001.md"))) == 1


def test_workers_building_the_vocabulary_at_once_do_not_fail(tmp_path, monkeypatch):
    """Trial batch b014: the workers of a batch in a new workspace built the missing vocabulary at the same time into
    one ocr_vocab.txt.tmp; one of them failed a file with "Permission denied". Each writes a temporary file of its
    own, and a replace the other process holds this moment is tried again."""
    d = tmp_path / "texts"
    d.mkdir()
    (d / "N-00001.md").write_text(f"=== page 1 ===\n\n{CLEAN}\n", encoding="utf-8")
    out = str(tmp_path / "ocr_vocab.txt")
    real, calls = os.replace, []

    def busy_once(src, dst):
        calls.append(src)
        if len(calls) == 1:
            raise PermissionError(13, "the other process has it open")
        return real(src, dst)

    monkeypatch.setattr(ocr_score.os, "replace", busy_once)
    monkeypatch.setattr(ocr_score.time, "sleep", lambda s: None)
    ocr_score.build_vocab(str(d), out, df_min=1)
    assert len(calls) == 2 and str(os.getpid()) in calls[0] and os.path.exists(out)
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
