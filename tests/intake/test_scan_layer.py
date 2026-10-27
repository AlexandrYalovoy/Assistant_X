# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The visible text layer of a scan is kept (audit 7, M-040): a page with a legible layer is read once and its
recognition dropped when the layer already has its words, else only the words the layer lacks are added; a page whose
every phrase appears twice gets the flag "doubled", the quality report lists it, the search weighs it less, and
intake redo accepts a text that is no longer doubled."""

import json
from pathlib import Path

import pymupdf

from assistant_x.core.formats import read_pages_info, write_pages_info
from assistant_x.intake import config as intake_cfg, ocr_redo, quality_report, work as intake_work
from assistant_x.intake.tools import assemble_md, convert_md, ocr_page, ocr_score
from tests.corpus import documents
from tests.intake.intake_fixtures import FONT

LAYER = documents.sentences(701, 4)
CAPTION = "Рисунок 5 Общий вид блочной установки комплексной подготовки продукции с узлом учета"


def _layer_scan(path, picture_lines, shift=4):
    """A page that is a picture of picture_lines with a visible text layer of LAYER put a little off the glyphs."""
    doc = pymupdf.open()
    page = documents.picture_page(doc, "\n".join(picture_lines))
    page.insert_textbox(
        pymupdf.Rect(56 + shift, 56 + shift, 540, 800), "\n".join(LAYER), fontsize=14, fontname="ru", fontfile=FONT
    )
    doc.save(path)


def _fake_recognise(lines):
    """recognise() that reads the given lines (a box for every word, one line each)."""

    def recognise(png, dpi, language, tmp, tag, psm=None):
        calls.append(psm)
        words = []
        for k, line in enumerate(lines):
            for i, w in enumerate(line.split()):
                words.append((100 + 120 * i, 100 + 60 * k, 100, 40, w, (1, 1, k)))
        text = "\n".join(lines)
        return {
            "words": words,
            "size": (2480, 3508),
            "text": text,
            "plain": text,
            "m": ocr_page.measure(text, [95.0] * len(words)),
        }

    calls = []
    recognise.calls = calls
    return recognise


def _convert(tmp_path, monkeypatch, pdf, read):
    monkeypatch.setattr(ocr_page, "tesseract_exe", lambda: "tesseract")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))  # no Tesseract here: PyMuPDF only looks for its data
    rec = _fake_recognise(read)
    monkeypatch.setattr(ocr_page, "recognise", rec)
    monkeypatch.setattr(ocr_page, "orientation", lambda *a, **k: (0, 0.0))
    ocr_page.DOCS.clear()
    cache, out, old = tmp_path / "cache", tmp_path / "md", tmp_path / "old"
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"T0001": {"parts": [[str(pdf), 1]]}}), encoding="utf-8")
    convert_md.main([str(jobs), str(cache), "0"])
    old.mkdir()
    (old / "T0001.txt").write_text("=== page 1 ===\n\n" + "\n".join(LAYER) + "\n", encoding="utf-8")
    assemble_md.main([str(old), str(cache), str(out), "T0001"])
    return (out / "T0001.md").read_text(encoding="utf-8"), read_pages_info(out / "T0001.pages.json"), rec.calls


def test_the_layer_of_a_scan_is_kept(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    _layer_scan(pdf, LAYER)
    md, info, calls = _convert(tmp_path, monkeypatch, pdf, LAYER)
    for s in LAYER:
        assert md.count(s[:40]) == 1, s
    assert info[1]["layer"] == "kept" and info[1]["source"] == "markdown"
    assert len(calls) == 1  # one reading: no orientation check, no retries


def test_only_the_words_the_layer_lacks_are_added(tmp_path, monkeypatch):
    pdf = tmp_path / "b.pdf"
    _layer_scan(pdf, LAYER + [CAPTION])
    md, info, _ = _convert(tmp_path, monkeypatch, pdf, [CAPTION] + LAYER[:1])
    assert md.count("комплексной подготовки") == 1 and md.count(LAYER[0][:40]) == 1
    assert info[1]["layer"] == "added"


def test_new_words_beside_the_layer():
    words = [(0, 0, 1, 1, w, 1) for w in ("Давление", "нефти", "Рисунок", "5")]
    assert [w[4] for w in ocr_page.new_words(words, {"давление", "нефти"})] == ["Рисунок", "5"]


def test_a_doubled_page_is_flagged_and_listed(tmp_path):
    once = " ".join(documents.sentences(702, 6))
    doubled = " ".join(s + " " + s for s in documents.sentences(703, 6))
    assert ocr_score.repeated(once) < 0.1 and ocr_score.repeated(doubled) >= ocr_score.DOUBLED
    md = f"=== page 1 ===\n\n{once}\n\n=== page 2 ===\n\n{doubled}\n"
    (tmp_path / "md").mkdir()
    write_pages_info(tmp_path / "md" / "T0001.pages.json", {1: {"flags": []}, 2: {"flags": []}})
    res = intake_work.ocr_measures(tmp_path, "T0001", md)
    assert res["ocr_doubled_pages"] == 1
    assert read_pages_info(tmp_path / "md" / "T0001.pages.json")[2]["flags"] == ["doubled"]
    m = {"pages": 2, "no_ocr_pages": 0, "fffd_per_1000": 0, "fffd": 0, "empty_pages": 0, "ocr_share": 0, "letters": {}}
    m.update(ocr_score=90, ocr_low_pages=0, ocr_garbled_pages=0, ocr_doubled_pages=1, fallback=0)
    assert ("re-extract the text", "high") in [p[1:] for p in quality_report.problems(m)]
    from assistant_x.search.retrieval import page_note

    assert "twice" in page_note(95, "doubled")


def test_consecutive_repeats_are_dropped():
    s = "Давление насыщения нефти определяют по пробам."
    assert assemble_md.drop_repeats(f"{s}\n{s}\nДругая строка текста здесь") == f"{s}\nДругая строка текста здесь"
    assert assemble_md.drop_repeats(f"{s} {s} Конец.") == f"{s} Конец."
    assert assemble_md.drop_repeats("| да | да | да |\n| да | да | да |").count("да") == 6  # table rows stay
    assert assemble_md.drop_repeats("Да нет.\nДа нет.") == "Да нет.\nДа нет."  # too short to tell


def test_redo_accepts_a_text_no_longer_doubled(tmp_path):
    clean = [" ".join(documents.sentences(704 + i, 3)) for i in range(8)]
    old = "".join(f"=== page {i} ===\n\n{s} {s}\n\n" for i, s in enumerate(clean, 1))
    new = "".join(f"=== page {i} ===\n\n{s}\n\n" for i, s in enumerate(clean, 1))
    (tmp_path / "X-00001.md").write_text(old, encoding="utf-8")
    r = {
        "code": "X-00001",
        "old": ocr_redo.words_score(old),
        "new": ocr_redo.words_score(new),
        "known": ocr_redo.known_words(new),
        "old_known": ocr_redo.known_words(old),
        "pages": 8,
        "variant": "pipeline",
        "old_doubled": ocr_redo.doubling(old),
        "doubled": ocr_redo.doubling(new),
    }
    assert r["old_doubled"][0] == 1.0 and r["doubled"][0] == 0.0
    assert ocr_redo.verdict(r, tmp_path, 10).startswith("recognized again: text replaced — no longer doubled")
    r["doubled"] = r["old_doubled"]
    assert "text kept" in ocr_redo.verdict(r, tmp_path, 10)


def test_redo_counts_known_words_once_per_page(tmp_path):
    """A text doubled word by word and phrase by phrase (a scan's layer interleaved with its recognition, as in run 2a:
    mean repeated share 0.3-0.5) keeps no more known words than its clean recognition; a text that lost words is kept."""
    clean = [" ".join(documents.sentences(720 + i, 3)) for i in range(6)]

    def interleave(s):
        ws = s.split()
        return " ".join(w for pair in zip(ws, ws) for w in pair)

    old = "".join(f"=== page {i} ===\n\n{interleave(s) if i % 2 else s + ' ' + s}\n\n" for i, s in enumerate(clean, 1))
    new = "".join(f"=== page {i} ===\n\n{s}\n\n" for i, s in enumerate(clean, 1))
    assert ocr_redo.known_words(old) == ocr_redo.known_words(new) > 0
    (tmp_path / "X-00002.md").write_text(old, encoding="utf-8")
    r = {
        "code": "X-00002",
        "old": ocr_redo.words_score(old),
        "new": ocr_redo.words_score(new),
        "known": ocr_redo.known_words(new),
        "old_known": ocr_redo.known_words(old),
        "pages": 6,
        "variant": "pipeline",
        "old_doubled": (0.3, 0.3),  # partly doubled: the halving of the old rule (1 - mean/2) kept such texts
        "doubled": (0.0, 0.0),
    }
    assert ocr_redo.verdict(r, tmp_path, 10).startswith("recognized again: text replaced — no longer doubled")
    half = "".join(f"=== page {i} ===\n\n{' '.join(s.split()[: len(s.split()) // 2])}\n\n" for i, s in enumerate(clean, 1))
    r["known"] = ocr_redo.known_words(half)
    assert "fewer known words" in ocr_redo.verdict(r, tmp_path, 10)


def test_redo_reads_the_page_images_only_for_a_broken_font_or_lost_words():
    md = f"=== page 1 ===\n\n{' '.join(documents.sentences(730, 4))}\n\n"
    layer, scan = {"pages": 1, "ocr_pages": 0}, {"pages": 1, "ocr_pages": 1}
    known, score = ocr_redo.known_words(md), ocr_redo.words_score(md)
    assert not ocr_redo.second_reading(md, layer, old_known=known)  # a clean layer text that kept its words
    assert ocr_redo.second_reading(md, layer, old_known=known, old_broken=True)  # a broken font of the old text
    assert ocr_redo.second_reading(md, layer, old_known=3 * known)  # the layer lost known words
    assert not ocr_redo.second_reading(md, scan, old_known=3 * known)  # a scan has no layer to blame
    assert ocr_redo.second_reading(md, layer, old_score=score + ocr_redo.REDO_LOSS + 1, old_known=known)  # poor layer
    assert not ocr_redo.second_reading(md, layer, old_score=score + 3, old_known=known)
    assert ocr_redo.best_variant({"pipeline": md, "page images": md}, known) == "pipeline"  # a tie: the first reading


def _redo_library(cfg, pages):
    """Library PDFs and doubled old texts of codes {code: pages} (every phrase of a page twice)."""
    lib = cfg.library / "01_Standards"
    lib.mkdir(parents=True, exist_ok=True)
    man = ["path\tsize\tchanged\tsha256\tcode"]
    for i, (code, n) in enumerate(pages.items()):
        doc = pymupdf.open()
        for _ in range(n):
            doc.new_page()
        doc.save(lib / f"{code}.pdf")
        man.append(f"library\\01_Standards\\{code}.pdf\t1\t-\tab\t{code}")
        old = "".join(
            f"=== page {p} ===\n\n{' '.join(documents.sentences(800 + 10 * i + p, 3))}\n"
            f"{' '.join(documents.sentences(800 + 10 * i + p, 3))}\n\n"
            for p in range(1, n + 1)
        )
        (cfg.index / "texts" / f"{code}.md").write_text(old, encoding="utf-8")
    (cfg.index / "manifest.tsv").write_text("\n".join(man) + "\n", encoding="utf-8")


def test_redo_reads_as_the_intake_and_writes_each_document_when_ready(project, monkeypatch):
    """redo runs prep, the OCR of a long scan in page ranges and convert on the pool as the intake does, with the
    scanned pages of prep; the biggest document first; each text is replaced once its document is read (results.jsonl
    keeps a line a document) and a second run with --reuse takes the finished readings without reading again."""
    from assistant_x.intake import process, schedule

    root, cfg = project
    pages = {"N-00001": 3, "N-00002": 2 * schedule.SHARD_MIN}
    _redo_library(cfg, pages)
    calls = []

    def prep(job):
        calls.append(("prep", job["tid"]))
        n = pages[job["tid"].split("_")[0]]
        return {
            "status": "prepped",
            "pages": n,
            "pdf": job["src"],
            "ocr_pages": n,
            "scan_pages": list(range(1, n + 1)),
            "picture_pages": [],
            "phrases": 0,
            "prep_seconds": 0.1,
        }

    def convert_shard(job):
        calls.append(("shard", job["tid"], tuple(job["pages"])))
        return {"status": "shard", "pages": job["pages"], "seconds": 1.0}

    def convert(job):
        calls.append(("convert", job["tid"], len(job.get("scan_pages") or [])))
        code, w = job["tid"].split("_")[0], Path(job["work"])
        (w / "md").mkdir(exist_ok=True)
        text = "".join(
            f"=== page {p} ===\n\n{' '.join(documents.sentences(800 + 10 * list(pages).index(code) + p, 3))}\n\n"
            for p in range(1, pages[code] + 1)
        )
        (w / "md" / f"{job['tid']}.md").write_text(text, encoding="utf-8")
        return {"status": "converted", "convert_seconds": 2.0}

    monkeypatch.setattr(intake_work, "prep", prep)
    monkeypatch.setattr(intake_work, "convert", convert)
    monkeypatch.setattr(intake_work, "convert_shard", convert_shard)
    monkeypatch.setattr(intake_cfg, "can_ocr", lambda c: True)
    monkeypatch.setattr(process, "regulated_pool", lambda *a, **k: (process.Inline(), 4))

    class A:
        codes, worst, below, dry_run, reuse = list(pages), None, None, False, None

    assert ocr_redo.cmd_redo(cfg, A()) == 0
    assert calls[0] == ("prep", "N-00002")  # the biggest first
    shards = [c for c in calls if c[0] == "shard"]
    assert len(shards) == schedule.shard_count(2 * schedule.SHARD_MIN, 4) > 1 and shards[0][1] == "N-00002"
    assert ("convert", "N-00002", 2 * schedule.SHARD_MIN) in calls  # the scanned pages of prep reach the conversion
    assert ("convert", "N-00001", 3) in calls
    for code in pages:
        new = (cfg.index / "texts" / f"{code}.md").read_text(encoding="utf-8")
        assert ocr_redo.doubling(new)[0] == 0  # replaced: no longer doubled
    work = next(cfg.work.glob("redo/*"))
    lines = [json.loads(ln) for ln in (work / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(r["code"] for r in lines) == list(pages) and all(r["replaced"] for r in lines)
    assert next(r for r in lines if r["code"] == "N-00002")["ranges"] == len(shards) and lines[0]["busy"] > 0
    calls.clear()
    A.reuse = str(work)
    for code in pages:  # the old texts back, as if the first run had been stopped before writing
        (cfg.index / "texts" / f"{code}.md").write_text(
            (cfg.inbox / "_to_delete" / next((cfg.inbox / "_to_delete").iterdir()).name / f"{code}.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
    assert ocr_redo.cmd_redo(cfg, A()) == 0
    assert not [c for c in calls if c[0] != "prep"]  # read before: no OCR, no conversion
    assert all(ocr_redo.doubling((cfg.index / "texts" / f"{c}.md").read_text(encoding="utf-8"))[0] == 0 for c in pages)


def test_a_phrase_repeated_many_times_is_no_doubled_text():
    """A legal-database text repeats its amendment note after every reference: many repeats, few pairs; a page
    extracted twice repeats everything exactly twice (round 1 of the pipeline test: 5 false pages in a 2015 GOST)."""
    note = "(ссылка введена Изменением N 1, введенным в действие Приказом Росстандарта от 07.04.2021 N 191-ст)"
    refs = [f"ГОСТ {33250 + i}-2015 {s}" for i, s in enumerate(documents.sentences(740, 8))]
    native = "\n\n".join(f"{r} {note}" for r in refs)
    clean = " ".join(documents.sentences(741, 4))
    assert ocr_score.repeated(native) >= ocr_score.DOUBLED and not ocr_score.is_doubled(native)
    assert ocr_score.is_doubled(f"{clean} {clean}")
