# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Convert library PDFs to per-page Markdown (layout analysis; scanned pages OCR'd in the document languages: the
"tesseract" codes of the language packs, core/lang.tesseract()).
Results are cached per chunk, so a restart skips finished chunks. A chunk that fails makes the exit code 1.
Usage: python -m assistant_x.intake.tools.convert_md <jobs.json> <cache_dir> [workers]
jobs.json: {"<code>": {"parts": [["<file.pdf>", <first_page>], ...], "force_ocr": false}, ...}
  "use_ocr": false in a job: no OCR (no Tesseract), pages without a text layer stay empty.
  workers 0: the chunks one after another in this process (a persistent worker of intake.py calls main()).
OCR goes through ocr_page.exec_ocr (the Tesseract program: word confidence, retries of weak pages, turned pages) when the
program is found, else through the Tesseract of PyMuPDF; the measures of the OCR pages of a chunk are written to
<cache_dir>/<code>/ocr/<chunk>.json ({page: ocr_page.STATS}) before the chunk itself.
A chunk holds up to TEXT_CHUNK pages of text or OCR_CHUNK scanned pages ("ocr_pages" of a job, from prep); the scanned
pages of a chunk get their first reading in one Tesseract process (ocr_page.prerecognise); a process keeps one open PDF
per document for its chunks."""

import sys, os, json, re, time
from concurrent.futures import ProcessPoolExecutor, as_completed

from assistant_x.core import lang
from assistant_x.intake.tools import onnx_threads
from assistant_x.intake.tools import ocr_page

TEXT_CHUNK, OCR_CHUNK = 50, 5
_open = {}  # path -> the open PDF of this process (one per document, a few at a time)


def open_pdf(path):
    import pymupdf

    if path not in _open:
        if len(_open) >= 2:
            _open.pop(next(iter(_open))).close()
        _open[path] = pymupdf.open(path)
    return _open[path]


def close_all():
    while _open:
        _open.popitem()[1].close()


def chunks(n, scans):
    """[[page indexes]] of a document of n pages: runs of text pages of up to TEXT_CHUNK, of scanned ones (scans) of up
    to OCR_CHUNK."""
    out, cur, kind = [], [], None
    for s in range(n):
        k = s in scans
        if cur and (k != kind or len(cur) >= (OCR_CHUNK if kind else TEXT_CHUNK)):
            out.append(cur)
            cur = []
        cur.append(s)
        kind = k
    if cur:
        out.append(cur)
    return out


def preread(doc, pages, language):
    """The first reading of the scanned pages of a chunk in one Tesseract process (ocr_page.PRE)."""
    import tempfile
    from assistant_x.intake.tools import ocr_score

    tmp = tempfile.mkdtemp(prefix="ax_ocrp_")
    groups = {}
    try:
        for i in pages:
            page = doc[i]
            if ocr_score.is_drawing(doc.page_count, page.rect.width * page.rect.height):
                continue  # a drawing sheet is read in its own way
            pix, _, empty, *_ = ocr_page.page_image(page, 300)
            if empty:
                continue
            png = os.path.join(tmp, f"{i}.png")
            ocr_page.gray(pix).save(png)
            groups.setdefault(round(pix.width / page.rect.width * 72), []).append((i, png))
        for dpi, items in groups.items():
            ocr_page.prerecognise(items, dpi, language)
    finally:
        for f in os.listdir(tmp):
            os.remove(os.path.join(tmp, f))
        os.rmdir(tmp)


def markdown(path, shift, pages, force_ocr, use_ocr=True, scans=()):
    """({page: Markdown}, {page: OCR measures}) of the pages (from 0) of a PDF; page numbers shifted by shift + 1.
    scans: the pages (from 0) read by OCR, read first in one Tesseract process."""
    import pymupdf4llm

    hook = ocr_page.exec_ocr if use_ocr and ocr_page.tesseract_exe() else None
    ocr_page.reset()
    doc = open_pdf(path)
    if hook and (force_ocr or scans):
        preread(doc, [p for p in pages if force_ocr or p in scans], lang.tesseract())
    res = {}
    for ch in pymupdf4llm.to_markdown(
        doc,
        pages=pages,
        page_chunks=True,
        use_ocr=use_ocr,
        force_ocr=force_ocr,
        ocr_language=lang.tesseract(),
        ocr_dpi=300,
        show_progress=False,
        ocr_function=hook,
    ):
        n = ch["metadata"]["page_number"]
        text = ocr_page.OVERRIDE.get(n - 1, ch["text"])  # a turned page: the text of the turned image
        plain, whole = ocr_page.PLAIN.get(n - 1, ("", False))
        # (a short scanned page counts too: with a stamp in its text layer the layout analysis keeps only the stamp)
        if len(words(plain)) >= ocr_page.MIN_WORDS and kept(words(plain), words(text)) < ocr_page.LOST_SHARE:
            # the layout analysis lost most of what was recognised (tables, captions read as a picture): the plain
            # text of Tesseract instead of a page read whole, after the Markdown of a page read in part
            text = plain if whole else text + "\n\n" + plain
            ocr_page.STATS[n - 1]["plain"] = "instead" if whole else "added"
        res[n + shift] = text  # assemble_md fixes the characters of the OCR font (ocr_page.FONT_FIX) on every page
    return res, {n + 1 + shift: st for n, st in ocr_page.STATS.items()}


def words(text):
    """Lower-case words of two letters or more (markup and table pipes aside)."""
    return [w.lower() for w in re.findall(r"[^\W\d_]{2,}", text)]


def kept(recognised, page):
    """Share of the recognised words (distinct) that are on the page."""
    want = set(recognised)
    return len(want & set(page)) / len(want) if want else 1.0


def write_json(obj, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, out)


def ocr_out(out):
    """File of the OCR measures beside a cache chunk: <code>/ocr/<chunk>.json."""
    return os.path.join(os.path.dirname(out), "ocr", os.path.basename(out))


def run(code, path, shift, pages, force_ocr, out, use_ocr=True, scans=()):
    onnx_threads.limit()
    res, stats = markdown(path, shift, pages, force_ocr, use_ocr, set(scans))
    write_json(stats, ocr_out(out))
    write_json(res, out)
    return code, len(pages)


def progress_path(cache, code, rng=None):
    """<cache>/<code>.progress.json: the pages of a document converted so far (intake status shows them, the files of
    its ranges <code>.<first>.progress.json added up)."""
    return os.path.join(cache, f"{code}.{rng[0]}.progress.json" if rng else f"{code}.progress.json")


def progress(cache, code, done, total, rng=None):
    try:
        write_json({"done": done, "total": total, "updated": time.time()}, progress_path(cache, code, rng))
    except OSError:
        pass  # a progress line is a help only


def main(argv):
    jobs, cache = json.load(open(argv[0], encoding="utf-8")), argv[1]
    workers = int(argv[2]) if len(argv) > 2 else 4
    tasks = []
    for code, job in jobs.items():
        os.makedirs(f"{cache}/{code}", exist_ok=True)
        for path, first in job["parts"]:
            n = open_pdf(path).page_count
            scans = (
                {p - first for p in job.get("ocr_pages") or [] if first <= p < first + n}
                if job.get("use_ocr", True)
                else set()
            )
            rng = job.get("range")  # a range of pages of a long scan: the chunks that start in it
            for part in chunks(n, scans):
                if rng and not rng[0] <= first + part[0] <= rng[1]:
                    continue
                out = f"{cache}/{code}/{first + part[0]:05d}.json"
                if not os.path.exists(out):
                    tasks.append(
                        (
                            code,
                            path,
                            first - 1,
                            part,
                            job.get("force_ocr", False),
                            out,
                            job.get("use_ocr", True),
                            sorted(scans & set(part)),
                        )
                    )
    total, done, failed, t0 = sum(len(t[3]) for t in tasks), 0, 0, time.time()
    print(f"pages to convert: {total}", flush=True)
    for code, job in jobs.items():
        progress(cache, code, 0, total, job.get("range"))
    if workers > 0:
        close_all()  # the pool processes open the documents themselves

    def finished(t, get):
        nonlocal done, failed
        try:
            code, k = get()
            done += k
            print(f"{done}/{total} pages, {time.time() - t0:.0f} s ({code})", flush=True)
            progress(cache, code, done, total, jobs[code].get("range"))
        except MemoryError:
            raise  # the worker is past its memory cap: intake.py restarts it
        except Exception as e:
            failed += 1
            print(f"ERROR {t[5]}: {e!r}", file=sys.stderr, flush=True)

    if workers > 0:
        with ProcessPoolExecutor(workers) as ex:
            futs = {ex.submit(run, *t): t for t in tasks}
            for f in as_completed(futs):
                finished(futs[f], f.result)
    else:
        try:
            for t in tasks:
                finished(t, lambda t=t: run(*t))
        finally:
            close_all()  # another tool of this process (reocr_empty) opens the document afresh
    if failed:
        sys.exit(f"pieces not converted: {failed} of {len(tasks)}")


if __name__ == "__main__":
    main(sys.argv[1:])
