# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Work on one file of an intake batch, run in a pool process of intake.py (or inline with --workers 0).
Functions take a job dict and return a dict of results; only the main process writes the state.

  prep(job)     original -> PDF (LibreOffice for office files and spreadsheets, PyMuPDF for pictures, e-books and
                texts, DjVuLibre for DjVu), the outline of the file (tools/outline.py), the sheets of a spreadsheet
                (tools/sheets.py), hidden text (hidden.py), text-layer fingerprint for the duplicate check
  convert(job)  PDF -> Markdown pages (convert_md, reocr_empty, assemble_md), measures of the text
  lib_fp(path)  fingerprint of a library text (cached by dupcheck)

job["inproc"]: the tools (hidden, convert_md, reocr_empty, assemble_md) run as functions in this process, a persistent
worker of pool.py that imported them once; its memory cap and the time limit of a task are kept by intake_pool.
Otherwise each tool is a python process of its own with its own limits (stage_mode "subprocess" in assistant_x.toml).
LibreOffice is a process of its own in both modes.
"""

import contextlib, gc, importlib, json, math, os, re, shutil, sys, time
from pathlib import Path

from assistant_x.core import lang
from assistant_x.core.formats import EXTENSIONS, PAGE_WORDS, PAGES_SUFFIX, escape_marker, extensions
from assistant_x.intake import config as intake_cfg
from assistant_x.intake.limits import limit_this_process, run
from assistant_x.intake.results import Convert, Job, Prep

TOOLS = "assistant_x.intake.tools"  # the tools run as python -m TOOLS.<name>
from assistant_x.intake.tools import dupcheck

PAGE_MARK_RX = re.compile(rf"(?m)^=== (?:{PAGE_WORDS}) \d+ ===$")

OFFICE = set(extensions("office"))  # core/formats.EXTENSIONS
IMAGES = set(extensions("image"))
PAGE_SIZE, FONT_SIZE = (595, 842), 11  # an e-book or a text is laid out on A4 pages: its page numbers stay the same
FILETYPE = {"htm": "html", "md": "txt", "markdown": "txt", "oxps": "xps"}  # PyMuPDF's name of the type of a file
TEXT_PAGE = 80  # characters of a text layer: less, with a picture on the page, means a scanned page
# a scanned page by its area: raster images cover SCAN_COVER of the page and its text layer is sparse (fewer characters
# per cm² than SCAN_DENSITY; a page of text has 4 and more), as a scan with a stamp, a header or a watermark in its
# text layer has it; a PDF made of an office file is judged by TEXT_PAGE only (a slide over a full-page picture)
SCAN_COVER = 0.7
SCAN_DENSITY = 1.0
CM2 = (72 / 2.54) ** 2  # square points in a cm²
GRID = 100  # cells per side of the grid the joined image boxes are measured on
# a broken font encoding (a code table read as another: "Àáâã" for Cyrillic) is seen on the first BROKEN_PAGES text
# pages before the conversion (at least BROKEN_LETTERS letters): BROKEN_FOREIGN of the letters are of no document
# language, or BROKEN_NONWORD of the words are unknown to the library vocabulary (when it is big enough to tell)
BROKEN_PAGES = 5
BROKEN_LETTERS = 200
BROKEN_FOREIGN = 0.3
BROKEN_NONWORD = 0.8
DOC_LETTER_RX = re.compile(f"[{lang.chars('letters')}]")
_job = None
_slot = None


def lo_profile():
    """LibreOffice profile of this process: a short path (paths inside a profile pass 260 characters under a deep
    work folder) and one slot per running process (two instances on one profile hand the work to each other)."""
    global _slot
    import tempfile

    base = Path(tempfile.gettempdir()) / "ax_lo"
    base.mkdir(exist_ok=True)
    if _slot is None:
        for k in range(64):
            f = open(base / f"{k}.lock", "a+b")
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                continue
            _slot = (k, f)  # the lock lives as long as this process
            break
        else:
            _slot = (f"p{os.getpid()}", None)
    return (base / str(_slot[0])).as_uri()


def init_worker(memory_mb, env, limit=True):
    """Pool initializer: memory cap for this process and the tool environment (Tesseract, fingerprint cache)."""
    global _job
    from assistant_x.intake import balance

    cls, cpu_mask = balance.from_env(env)
    cls = 0 if cls == balance.PRIORITIES["normal"] else cls
    _job = limit_this_process(memory_mb, cls, cpu_mask) if limit else None
    os.environ.update(env)
    balance.limit_threads()
    if cls:
        balance.low_io()
    dupcheck.TESSERACT = env.get("TESSERACT", dupcheck.TESSERACT)


def _link(src, dst):
    """Hard link (same disk, no copy) or copy: tools get a short path without Cyrillic folders."""
    if dst.exists():
        return
    try:
        os.link(intake_cfg.lp(src), dst)
    except OSError:
        shutil.copy2(intake_cfg.lp(src), dst)


def _tool(name, *args, job, log, timeout, mem=None):
    """(None | the error dict of the file, None | "timeout" | "memory" | "code"). A tool that stops with a code other
    than 0 is an error of the file: its text would otherwise silently fall back to the plain text layer."""
    start = os.path.getsize(log) if os.path.exists(log) else 0
    if job.get("inproc"):
        try:
            rc, why = _call(name, args, log), None
        except MemoryError:
            raise  # past the memory cap of the worker: intake_pool reports it and restarts the worker
        except Exception as e:  # noqa: BLE001 — a tool that raises is an error of the file, as a crashed process would be
            _trace(log, e)
            err = {"status": "error", "why": f"{KIND[name]}: {error_text(e)}"[:300] + f" (see log/{Path(log).stem}.log)"}
            if memory_like(e):
                err["retry"] = "memory"
            return err, "code"
    else:
        cmd = [*tool_cmd(name), *map(str, args)]
        rc, why = run(cmd, timeout=timeout, memory_mb=mem if mem is not None else job["memory_mb"], log=log, env=job["env"])
    if why:
        return _fail(why, KIND[name]), why
    if rc != 0:
        tail = _tail(log, start)
        return {
            "status": "error",
            "why": f"{KIND[name]}: code {rc}" + (f": {tail}" if tail else "") + f" (see log/{Path(log).stem}.log)",
        }, "code"
    return None, None


def tool_cmd(name):
    """The command of a tool run as its own process (-I ignores PYTHONUTF8, hence -X utf8)."""
    return [sys.executable, "-X", "utf8", "-I", "-m", f"{TOOLS}.{name[:-3]}"]


def _call(name, args, log):
    """Exit code of a tool run as main(argv) in this process; its output goes to the log as a process's would."""
    mod = importlib.import_module(f"{TOOLS}.{name[:-3]}")
    with (
        open(log, "a", encoding="utf-8", errors="replace") as out,
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(out),
    ):
        try:
            mod.main([str(a) for a in args])
        except SystemExit as e:
            if isinstance(e.code, str):
                print(e.code, file=out)
            return e.code if isinstance(e.code, int) else 0 if e.code is None else 1
        finally:
            gc.collect()  # PDFs the tool left open: Windows keeps such files locked
    return 0


def task_timeout(fn, args):
    """Seconds a task of a persistent worker may take (intake_pool kills the worker past it): the limits of its tools."""
    from assistant_x.core.config import INTAKE

    t = {**INTAKE["timeouts"], **(args[0].get("timeouts", {}) if args and isinstance(args[0], dict) else {})}
    if fn.__name__ == "prep":
        return t["soffice"] + t["hidden"] + 600
    job = args[0] if args and isinstance(args[0], dict) else {}
    page = t.get("page") or 0
    if fn.__name__ == "convert":
        n = job.get("page_count") or 0
        return min(2 * t["convert"] + 1800, page * n + 900) if page and n else 2 * t["convert"] + 1800
    if fn.__name__ == "convert_shard" and page and job.get("pages"):
        a, b = job["pages"]
        return min(3600, page * (b - a + 1) + 600)  # a pathological page cannot hold a worker for an hour
    return 3600


KIND = {
    "convert_md.py": "conversion to Markdown",
    "reocr_empty.py": "OCR of empty pages",
    "assemble_md.py": "assembling the Markdown",
    "hidden.py": "the hidden text check",
}


def _tail(log, start, lines=3):
    """Last lines a tool wrote to the log (its stderr goes there too), in one line."""
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            f.seek(start)
            out = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        return ""
    return " | ".join(out[-lines:])[-300:]


def _fail(why, kind):
    """The error dict of a tool stopped by its limit; past the memory cap it asks for one more try with a double cap
    (process.Batch: the same path as a worker killed for memory)."""
    err = {"status": "error", "why": f"{kind}: {'time exceeded' if why == 'timeout' else 'memory cap exceeded'}"}
    if why == "memory":
        err["retry"] = "memory"
    return err


# MuPDF reports a failed allocation as FzErrorSystem (its "system" error class): a memory failure, not a broken file
MEMORY_ERRORS = ("MemoryError", "FzErrorSystem")


def error_text(e):
    """The text of an exception for a file's reason: str(e), else the name of its type (never a repr: the repr of a
    MuPDF error is the address of a SWIG proxy)."""
    return str(e).strip() or type(e).__name__


def memory_like(e):
    """True for an exception that is worth one more try with more memory."""
    from assistant_x.intake.pool import TaskError

    kind = e.kind if isinstance(e, TaskError) else type(e).__name__
    text = str(e).lower()
    return kind in MEMORY_ERRORS or "out of memory" in text or "malloc" in text


def _trace(log, e):
    """The traceback of an exception appended to the file's log."""
    import traceback

    try:
        with open(log, "a", encoding="utf-8", errors="replace") as f:
            f.write("".join(traceback.format_exception(e)))
    except OSError:
        pass


def soffice_env(env):
    """The environment of LibreOffice: without the PYTHON* variables of our tools and of the host, and without the
    venv launcher variable — its bundled Python takes them for its own and fails to start ("Could not find platform
    independent libraries")."""
    return {
        k: v for k, v in (env or os.environ).items() if not k.upper().startswith("PYTHON") and k != "__PYVENV_LAUNCHER__"
    }


def _cells(a, b, origin, size):
    """The range of grid cells along one side whose centres lie within [a, b]."""
    return (max(0, math.ceil((a - origin) / size * GRID - 0.5)), min(GRID, math.floor((b - origin) / size * GRID - 0.5) + 1))


def image_cover(page):
    """Share of the page area its raster images cover (their boxes joined and clipped to the page), or None when
    PyMuPDF gives no boxes for the images the page has."""
    r = page.rect
    try:
        boxes = [b["bbox"] for b in page.get_image_info()]
    except Exception:  # noqa: BLE001 — a page whose images do not read is judged by its text
        return None
    if not boxes:
        return None if page.get_images() else 0.0
    if r.width <= 0 or r.height <= 0:
        return None
    cells = bytearray(GRID * GRID)
    for x0, y0, x1, y1 in boxes:
        c0, c1 = _cells(max(x0, r.x0), min(x1, r.x1), r.x0, r.width)
        r0, r1 = _cells(max(y0, r.y0), min(y1, r.y1), r.y0, r.height)
        for row in range(r0, r1):
            if c1 > c0:
                cells[row * GRID + c0 : row * GRID + c1] = b"\1" * (c1 - c0)
    return sum(cells) / len(cells)


def scanned(page, text, by_area=True):
    """A page to read by OCR: raster images over SCAN_COVER of it with a sparse text layer (a stamp, a header), or
    almost no text layer and a picture on it (a short page of an office file is not a scan)."""
    chars = len(text.strip())
    cover = image_cover(page) if by_area else None
    if cover is None:
        return chars < TEXT_PAGE and bool(page.get_images())
    area = page.rect.width * page.rect.height / CM2
    return (cover >= SCAN_COVER and chars / max(area, 1) < SCAN_DENSITY) or (chars < TEXT_PAGE and cover > 0)


def broken_encoding(doc, by_area=True):
    """Why the text layer looks like a font read with a wrong code table, or "": on the first BROKEN_PAGES text pages
    the letters of no document language (the letters of the active language packs), the lost symbols, or the words
    the library vocabulary does not know. Seen before the conversion, so the page images are recognised at once."""
    from assistant_x.intake.tools import ocr_score

    pages = []
    for page in doc:
        text = page.get_text()
        if len(text.strip()) >= TEXT_PAGE and not scanned(page, text, by_area):
            pages.append(text)
            if len(pages) >= BROKEN_PAGES:
                break
    body = "\n".join(pages)
    letters = [c for c in body if c.isalpha()]
    if len(letters) < BROKEN_LETTERS:
        return ""
    foreign = sum(not DOC_LETTER_RX.match(c) for c in letters) / len(letters)
    if foreign >= BROKEN_FOREIGN:
        return f"{foreign:.0%} of the letters are of no document language"
    lost = body.count("\ufffd") / len(letters)
    if lost >= 0.1:
        return f"{lost:.0%} lost symbols"
    vocab_file = ocr_score.vocab_file()
    if os.path.exists(vocab_file):  # the vocabulary is not built here: a new library has none
        vocab = ocr_score.load_vocab(vocab_file)
        n, bad, _ = ocr_score.word_counts(body, vocab)
        if len(vocab[0]) >= ocr_score.MIN_VOCAB_WORDS and n >= 50 and bad / n >= BROKEN_NONWORD:
            return f"{bad / n:.0%} of the words unknown to the library"
    return ""


def soffice(job, src, outdir, fmt, log):
    """LibreOffice converts src into outdir/<stem>.<fmt>; None, or the error dict of the file."""
    rc, why = run(
        [
            job["soffice"],
            f"-env:UserInstallation={lo_profile()}",
            "--headless",
            "--norestore",
            "--convert-to",
            fmt,
            "--outdir",
            outdir,
            src,
        ],
        timeout=job["timeouts"]["soffice"],
        memory_mb=job["memory_mb"],
        log=log,
        env=soffice_env(job["env"]),
    )
    if why:
        return _fail(why, "LibreOffice")
    if not (Path(outdir) / f"{Path(src).stem}.{fmt}").exists():
        return {
            "status": "error",
            "why": f"LibreOffice did not convert it to {fmt} (code {rc}, see log/{Path(log).stem}.log)",
        }
    return None


def decode_text(data):
    """The text of a plain-text file: UTF-8 (or UTF-16 with its mark), else the legacy code page of a language pack
    ("encodings" of the packs) that gives the most stop words, then letters, of the document languages."""
    from assistant_x.core.common import letter_counts

    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    stop = set(lang.words("stop_words"))
    best = ((-1, -1), data.decode("latin-1"))
    for enc in dict.fromkeys(lang.words("encodings")):
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # the stop words of the languages first: two Cyrillic code pages give as many letters, but one of them in the
        # wrong case
        score = (sum(w in stop for w in re.findall(r"[^\W\d_]+", text[:20000])), letter_counts(text)[0])
        best = max(best, (score, text), key=lambda x: x[0])
    return best[1]


def reflow_to_pdf(src, pdf, ext):
    """An e-book (EPUB, FB2, MOBI, XPS) or a text (TXT, Markdown as it is, HTML) as a PDF of A4 pages, its bookmarks
    kept; None, or the error dict of the file."""
    import pymupdf

    try:
        if EXTENSIONS.get(ext) == "text" and FILETYPE.get(ext, ext) == "txt":
            doc = pymupdf.open(stream=decode_text(Path(src).read_bytes()).encode("utf-8"), filetype="txt")
        else:
            doc = pymupdf.open(stream=Path(src).read_bytes(), filetype=FILETYPE.get(ext, ext))
        if doc.is_reflowable:
            doc.layout(width=PAGE_SIZE[0], height=PAGE_SIZE[1], fontsize=FONT_SIZE)
        toc = doc.get_toc()
        out = pymupdf.open("pdf", doc.convert_to_pdf())
        if toc:
            try:
                out.set_toc([t for t in toc if 1 <= t[2] <= out.page_count])
            except (ValueError, RuntimeError):
                pass  # a broken outline of the book: the text still goes in
        out.save(pdf, garbage=3, deflate=True)
    except Exception as e:  # noqa: BLE001 — a file PyMuPDF cannot read is an error of the file
        return {"status": "error", "why": f".{ext} not laid out as PDF: {e!r}"[:300]}
    return None


def sheets_of(job, src, ext, w, log):
    """The sheets of a spreadsheet as Markdown into <work>/sheets/<tid>.json ([[name, Markdown, probe values]]);
    XLS, XLSB and ODS are made XLSX by LibreOffice first. None, or the error dict of the file."""
    from assistant_x.intake.tools import sheets

    book = src
    if ext not in ("xlsx", "xlsm"):
        (w / "xlsx").mkdir(exist_ok=True)
        book = w / "xlsx" / f"{Path(src).stem}.xlsx"
        if not book.exists():
            err = soffice(job, src, w / "xlsx", "xlsx", log)
            if err:
                return err
    try:
        found = sheets.sheets_markdown(book)
    except Exception as e:  # noqa: BLE001 — the PDF of the book still carries its text
        found = []
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"the cells of the sheets were not read: {e!r}\n")
    (w / "sheets").mkdir(exist_ok=True)
    (w / "sheets" / f"{job['tid']}.json").write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return None


def has_text_layer(pdf):
    """True when some page of the PDF has text (visible or not: an invisible one is what the hidden check looks for)."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return any(page.get_text().strip() for page in doc)


def prep(job: Job) -> Prep:
    import pymupdf

    t0 = time.time()
    w, tid, ext = Path(job["work"]), job["tid"], job["ext"]
    for d in ("src", "pdf", "log"):
        (w / d).mkdir(parents=True, exist_ok=True)
    log = w / "log" / f"{tid}.log"
    src = w / "src" / f"{tid}.{ext}"
    if not job.get("imgocr"):
        _link(job["src"], src)
    pdf = w / "pdf" / f"{tid}.pdf"
    kind = EXTENSIONS.get(ext, "")
    if ext == "pdf":
        pdf = src
    elif kind in ("office", "spreadsheet"):
        if not job.get("soffice"):
            return {"status": "skipped", "why": f"no LibreOffice: .{ext} not converted to PDF (assistant-x setup-intake)"}
        if not pdf.exists():
            err = soffice(job, src, w / "pdf", "pdf", log)
            if err:
                return err
        if kind == "spreadsheet":
            err = sheets_of(job, src, ext, w, log)
            if err:
                return err
    elif ext == "chm":  # a help file: its pages as one HTML, laid out like any HTML
        if not pdf.exists():
            from assistant_x.intake.tools import chm

            page = w / "chm" / f"{tid}.html"
            err = chm.to_html(src, page, job.get("sevenzip"), w / "chm" / tid, job["timeouts"]["unpack"])
            if err:
                return err
            err = reflow_to_pdf(page, pdf, "html")
            if err:
                return err
    elif kind in ("ebook", "text"):
        if not pdf.exists():
            err = reflow_to_pdf(src, pdf, ext)
            if err:
                return err
    elif kind == "djvu":
        if not job.get("ddjvu"):
            return {
                "status": "skipped",
                "why": f"no DjVuLibre (the program ddjvu): .{ext} not converted to PDF; install "
                "DjVuLibre or give its ddjvu in assistant_x.toml [intake] ddjvu",
            }
        if not pdf.exists():
            rc, why = run(
                [job["ddjvu"], "-format=pdf", src, pdf],
                timeout=job["timeouts"]["soffice"],
                memory_mb=job["memory_mb"],
                log=log,
                env=job["env"],
            )
            if why:
                return _fail(why, "DjVuLibre")
            if not pdf.exists():
                return {"status": "error", "why": f"DjVuLibre did not convert it (code {rc}, see log/{tid}.log)"}
    elif ext in IMAGES:
        if not pdf.exists():
            img = pymupdf.open(src)
            pymupdf.open("pdf", img.convert_to_pdf()).save(pdf)
    else:
        return {
            "status": "skipped",
            "why": f"the pipeline does not process .{ext}: decide by hand (a part of a document, reject)",
        }
    try:
        n = pymupdf.open(pdf).page_count
    except Exception as e:  # noqa: BLE001 — a PDF that does not open is an error of the file
        _trace(log, e)
        err = {"status": "error", "why": f"the PDF does not open: {error_text(e)}"[:300]}
        if memory_like(e):
            err["retry"] = "memory"
        return err
    res: Prep = {"status": "prepped", "pages": n, "hidden": 0, "hidden_pages": []}
    if not job.get("imgocr"):  # the bookmarks of the PDF or the heading styles of a DOCX: the first source of the outline
        from assistant_x.intake.tools import outline

        given = outline.of_file(pdf, src)
        if given:
            (w / "outline").mkdir(exist_ok=True)
            (w / "outline" / f"{tid}.json").write_text(json.dumps(given, ensure_ascii=False), encoding="utf-8")
    by_area = kind in ("pdf", "image", "djvu")  # a PDF the pipeline made of a text has no scans
    imgocr = job.get("imgocr")
    if not imgocr and job.get("ocr"):
        with pymupdf.open(pdf) as d:
            why = broken_encoding(d, by_area)
        if why:
            imgocr = True
            res.update(imgocr=True, why=f"broken font encoding ({why}), recognizing the page images")
    if imgocr:  # broken font encoding: OCR page images instead of the text layer
        cache = w / "cache" / tid
        if cache.exists():
            for f in [*cache.glob("*.json"), *cache.glob("ocr/*.json")]:
                f.unlink()
        sd, im = pymupdf.open(pdf), pymupdf.open()
        for pg in sd:
            pix = pg.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
            npg = im.new_page(width=pg.rect.width, height=pg.rect.height)
            npg.insert_image(npg.rect, pixmap=pix)
        pdf = w / "pdf" / f"{tid}.img.pdf"
        im.save(pdf, deflate=True)
    elif not has_text_layer(pdf):
        pass  # page images only: no text at all, so none a reader does not see (the hidden text check is skipped)
    else:
        # text a reader does not see (planted instructions): report it and convert a copy without it
        rep, clean = w / "log" / f"{tid}.hidden.json", w / "pdf" / f"{tid}.clean.pdf"
        err, why = _tool(
            "hidden.py", pdf, "--clean", clean, "--json", rep, job=job, log=log, timeout=job["timeouts"]["hidden"]
        )
        if why == "code":
            return err  # the check crashed: the file must not pass as checked
        try:
            hid = json.loads(rep.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hid = {}
        res.update(hidden=hid.get("hidden") or 0, hidden_pages=hid.get("hidden_pages", [])[:20])
        if why:
            res["hidden_check"] = f"the hidden text check did not finish: {why}"
        if hid.get("hidden") and clean.exists():
            pdf = clean
    doc = pymupdf.open(pdf)
    # a word broken at the end of a line with a hyphen is joined by PyMuPDF (the hyphen of a soft break is dropped)
    texts = [p.get_text(flags=pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_DEHYPHENATE) for p in doc]
    heavy = vector_pages(doc, texts, 0 if job.get("flatten_all") else VECTOR_MAX) if job.get("ocr") else []
    if heavy:  # the layout analysis would take minutes a page: the page images go instead (scans of the copy)
        flat = w / "pdf" / f"{tid}.flat.pdf"
        flatten(doc, heavy, flat)
        doc.close()
        pdf, doc = flat, pymupdf.open(flat)
        res.update(flattened=heavy)
    # the scanned pages: convert reads them by OCR even when a stamp or a header gives them some text layer
    scans = [i + 1 for i, (p, t) in enumerate(zip(doc, texts)) if scanned(p, t, by_area or bool(heavy))]
    # the other pages with a picture: OCR reads the picture once (ocr_page.beside_layer), the order of the work counts it
    pictures = [i + 1 for i, p in enumerate(doc) if i + 1 not in set(scans) and p.get_images()]
    sheets = sheet_pages(doc, texts, scans)
    res.update(ocr_pages=len(scans), scan_pages=scans, image_pages=len(pictures), picture_pages=pictures)
    res.update(sheet_pages=sheets)
    fp = dupcheck.fingerprint("\n".join(texts[:30]))
    res.update(pdf=str(pdf), fp=sorted(fp), phrases=len(fp), prep_seconds=round(time.time() - t0, 1))
    # plain text of the text layer: the fallback of assemble_md for pages the layout analysis loses
    (w / "txt").mkdir(exist_ok=True)
    with open(w / "txt" / f"{tid}.txt", "w", encoding="utf-8") as f:
        for i, t in enumerate(texts):
            f.write(f"\n=== page {i + 1} ===\n{escape_marker(t.strip())}\n")
    return res


VECTOR_MAX = 20000  # vector paths of a page without a text layer past which it is read from its image
FLAT_PIXELS = 12000  # the longer side of the image of such a page at most (300 dpi on A1, about 130 dpi on 2.4 m)


def vector_pages(doc, texts, limit=VECTOR_MAX):
    """The pages (from 1) without a text layer drawn of more than VECTOR_MAX vector paths: a drawing sheet whose text is
    curves, a scheme of 2 x 6 m. The layout analysis of pymupdf4llm took more than 10 minutes on one of 88 000 paths
    (trial batch b061: a project volume of 174 pages, 40 minutes); its image renders in half a second. limit 0: every
    page without a text layer and a picture (after the watchdog stopped a conversion)."""
    out = []
    for i, (p, text) in enumerate(zip(doc, texts)):
        if len(text.strip()) >= TEXT_PAGE or p.get_images():
            continue
        count = p.get_cdrawings if hasattr(p, "get_cdrawings") else p.get_drawings
        if len(count()) > limit:
            out.append(i + 1)
    return out


def flatten(doc, pages, out):
    """A copy of doc with the given pages (from 1) as gray images, the other pages as they are."""
    import pymupdf

    new = pymupdf.open()
    for i, page in enumerate(doc):
        if i + 1 not in pages:
            new.insert_pdf(doc, from_page=i, to_page=i)
            continue
        zoom = min(300 / 72, FLAT_PIXELS / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
        new.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, pixmap=pix)
    new.save(out, garbage=3, deflate=True)


def sheet_pages(doc, texts, scans=()):
    """The drawing sheets (A2 and up) whose text is drawn as curves (pages from 1): no picture, no text layer, but OCR
    reads each for half a minute (trial batches b026-b029: a set of 16-18 sheets went to one worker as a cheap task,
    450-500 s). schedule.cost counts them and a set of them is cut into page ranges."""
    from assistant_x.intake.tools import ocr_score

    skip = set(scans)
    return [
        i + 1
        for i, (p, text) in enumerate(zip(doc, texts))
        if i + 1 not in skip and ocr_score.is_sheet(p.rect.width * p.rect.height) and len(text.strip()) < TEXT_PAGE
    ]


def _convert_jobs(job, pages=None):
    """The jobs file of convert_md for a file (jobs/<tid>.json), or for a range of its pages (jobs/<tid>.<a>-<b>.json:
    only the chunks that start in the range are converted)."""
    w, tid = Path(job["work"]), job["tid"]
    (w / "jobs").mkdir(parents=True, exist_ok=True)
    # the printed page labels come from the original PDF: the copy read as page images (imgocr) has none
    original = w / "src" / f"{tid}.pdf"
    one = {
        "parts": [[job["pdf"], 1]],
        "force_ocr": False,
        "use_ocr": bool(job.get("ocr")),
        "ocr_pages": job.get("scan_pages") or [],
        # their chunks are short, as OCR reads them (a drawing sheet too)
        "picture_pages": sorted(set(job.get("picture_pages") or []) | set(job.get("sheet_pages") or [])),
        "label_pdf": str(original if original.exists() else job["pdf"]),
    }
    if pages:
        one["range"] = list(pages)
    path = w / "jobs" / (f"{tid}.{pages[0]}-{pages[1]}.json" if pages else f"{tid}.json")
    path.write_text(json.dumps({tid: one}), encoding="utf-8")
    return path


def convert_shard(job):
    """The OCR of a range of pages of a long scan (job["pages"]: [first, last]) into the cache of convert_md, as a task
    of its own (schedule.py); convert() of the file then finds those chunks done. An error is reported, not final: the
    conversion of the file reads what a range left out."""
    t0 = time.time()
    w, tid = Path(job["work"]), job["tid"]
    for d in ("cache", "log"):
        (w / d).mkdir(parents=True, exist_ok=True)
    log = w / "log" / f"{tid}.log"
    jobs = _convert_jobs(job, job["pages"])
    err, _ = _tool("convert_md.py", jobs, w / "cache", "0", job=job, log=log, timeout=job["timeouts"]["convert"])
    return err or {"status": "shard", "pages": job["pages"], "seconds": round(time.time() - t0, 1)}


def convert(job: Job) -> Convert:
    t0 = time.time()
    w, tid = Path(job["work"]), job["tid"]
    for d in ("jobs", "cache", "md", "mdtmp"):
        (w / d).mkdir(parents=True, exist_ok=True)
    log = w / "log" / f"{tid}.log"
    ocr = bool(job.get("ocr"))
    jobs = _convert_jobs(job)
    # processes of convert_md and reocr_empty; a persistent worker converts the chunks itself (its ONNX threads instead)
    threads = "0" if job.get("inproc") else str(job.get("ocr_threads") or 1)
    tmo = job["timeouts"]["convert"]
    err, _ = _tool("convert_md.py", jobs, w / "cache", threads, job=job, log=log, timeout=tmo)
    if err:
        return err
    if ocr:
        err, _ = _tool("reocr_empty.py", jobs, w / "cache", threads, job=job, log=log, timeout=tmo)
        if err:
            return err
    tmp = w / "mdtmp" / tid
    tmp.mkdir(exist_ok=True)
    err, _ = _tool("assemble_md.py", w / "txt", w / "cache", tmp, "--jobs", jobs, tid, job=job, log=log, timeout=1800)
    if err:
        return err
    try:
        rep = json.loads((tmp / "_report.json").read_text(encoding="utf-8"))[tid]
    except (OSError, ValueError, KeyError):
        rep = {}
    out = w / "md" / f"{tid}.md"
    if (tmp / f"{tid}.md").exists():
        os.replace(tmp / f"{tid}.md", out)
    if (tmp / f"{tid}{PAGES_SUFFIX}").exists():  # what is known of every page goes with the text
        os.replace(tmp / f"{tid}{PAGES_SUFFIX}", w / "md" / f"{tid}{PAGES_SUFFIX}")
    finish_text(w, tid)
    mark_pages(w, tid, "dpi_reduced", dpi_reduced(log))
    md = out.read_text(encoding="utf-8") if out.exists() else ""
    from assistant_x.core.common import letter_shares  # the share of the letters of every language pack

    res: Convert = {
        "status": "converted" if md else "error",
        "chars": len(md),
        "fffd": md.count("�"),
        "letters": {c: round(s, 2) for c, s in letter_shares(md).items()},
        "fallback": rep.get("old_text"),
        "tables": rep.get("tables"),
        "invisible_chars": rep.get("invisible_chars"),
        "no_ocr_pages": 0 if ocr else int(job.get("ocr_pages") or 0),
        "convert_seconds": round(time.time() - t0, 1),
    }
    if not md:
        res["why"] = f"no text obtained (see log/{tid}.log)"
    if md:
        res.update(ocr_measures(w, tid, md))
    if md and job.get("phrases", 0) < 30:  # a scan: the duplicate check needs the recognised text
        fp = dupcheck.fingerprint("\n".join(PAGE_MARK_RX.split(md)[1:31]))
        res.update(fp=sorted(fp), phrases=len(fp))
    return res


# pymupdf4llm prints it when a page is too large to be read at the resolution asked: the page of the "OCR on
# page.number=N" line before it (0-based) is the one read at a lower resolution
DPI_RX = re.compile(r"OCR on page\.number=(\d+)|Page too large for dpi=\d+")


def dpi_reduced(log):
    """The pages (1-based) the log of a file says OCR read at a reduced resolution; approximate when the chunks of a
    document were read in parallel (their lines interleave)."""
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    pages, last = set(), None
    for m in DPI_RX.finditer(text):
        if m.group(1) is not None:
            last = int(m.group(1)) + 1
        elif last is not None:
            pages.add(last)
    return sorted(pages)


def mark_pages(w, tid, flag, pages):
    """Add a flag to pages of <tid>.pages.json (core/formats.PAGE_FLAGS)."""
    from assistant_x.core.formats import read_pages_info, read_outline, write_pages_info

    side = w / "md" / f"{tid}{PAGES_SUFFIX}"
    info = read_pages_info(side) if pages else None
    if not info:
        return
    for p in pages:
        if p in info:
            flags = [f for f in (info[p].get("flags") or []) if f != flag]
            info[p]["flags"] = flags + [flag]
    write_pages_info(side, info, read_outline(side))


def finish_text(w, tid):
    """What prep found besides the pages: the outline of the file goes into <tid>.pages.json ("outline"), every sheet
    of a spreadsheet into the text as a Markdown table ("## Sheet: name") at the end of the page that shows its first
    cells (the first page when none does)."""
    from assistant_x.core.common import split_pages
    from assistant_x.core.formats import read_pages_info, write_pages_info
    from assistant_x.intake.tools.assemble_md import page_flags

    md, side = w / "md" / f"{tid}.md", w / "md" / f"{tid}{PAGES_SUFFIX}"
    given_f, sheets_f = w / "outline" / f"{tid}.json", w / "sheets" / f"{tid}.json"
    if not md.exists() or not (given_f.exists() or sheets_f.exists()):
        return
    given = json.loads(given_f.read_text(encoding="utf-8")) if given_f.exists() else None
    info = read_pages_info(side) or {}
    if sheets_f.exists():
        pages = [(n, body.strip("\n")) for n, body in split_pages(md.read_text(encoding="utf-8"))]
        if pages:
            bodies = dict(pages)
            for name, table, probe in json.loads(sheets_f.read_text(encoding="utf-8")):
                n = next((n for n, b in pages if any(p in b for p in probe)), pages[0][0])
                bodies[n] = (bodies[n] + f"\n\n## Sheet: {name}\n\n{table}").strip("\n")
                if n in info:
                    info[n]["flags"] = page_flags(bodies[n])
            md.write_text(
                "\n".join(f"=== page {n} ===\n\n{escape_marker(bodies[n])}\n" for n, _ in pages),
                encoding="utf-8",
                newline="\n",
            )
    if info:
        write_pages_info(side, info, given)


def ocr_measures(w, tid, md):
    """Recognition score of a text (tools/ocr_score.py) with the Tesseract confidence of its OCR pages (convert_md
    writes it to cache/<tid>/ocr/); the page by page details go to <work>/ocr/<tid>.json."""
    from assistant_x.intake.tools import ocr_score

    stats = {}
    for f in sorted((w / "cache" / tid / "ocr").glob("*.json")):  # z_force_* (empty pages read again) come last
        try:
            stats.update({int(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()})
        except (OSError, ValueError):
            continue
    sc = ocr_score.score_text(md, stats)
    (w / "ocr").mkdir(exist_ok=True)
    detail = {
        "score": sc["score"],
        "nonword": sc["nonword"],
        "words": sc["words"],
        "pages": [
            {**p, **{k: stats[p["page"]][k] for k in ("tried", "osd", "seconds") if k in stats.get(p["page"], {})}}
            for p in sc["pages"]
        ],
    }
    (w / "ocr" / f"{tid}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=0), encoding="utf-8")
    garbled = [p["page"] for p in sc["pages"] if p["words"] >= 20 and p["bad"] / p["words"] > ocr_score.GARBLED]
    mark_pages(w, tid, "garbled", garbled)
    doubled = [p["page"] for p in sc["pages"] if ocr_score.doubled_page(p)]
    mark_pages(w, tid, "doubled", doubled)
    confs = [s["conf"] for s in stats.values() if s.get("conf") is not None]
    lim = ocr_score.QUALITY["ocr_note"]
    return {
        "ocr_score": sc["score"],
        "ocr_nonword": sc["nonword"],
        "ocr_low_pages": sum(p["score"] is not None and p["score"] < lim and p["words"] >= 20 for p in sc["pages"]),
        "ocr_conf": round(sum(confs) / len(confs), 1) if confs else None,
        "ocr_retried": sum(len(s.get("tried", {})) > 1 for s in stats.values()),
        "ocr_rotated": sum(bool(s.get("rotate")) for s in stats.values()),
        "ocr_seconds": round(sum(s.get("seconds") or 0 for s in stats.values()), 1),
        "ocr_garbled_pages": len(garbled),
        "ocr_doubled_pages": len(doubled),
        "ocr_layer_kept": sum(s.get("layer") == "kept" for s in stats.values()),
        # a drawing sheet (ocr_page read it as one): its score is no sign of a bad scan
        "drawing": bool(stats) and all(s.get("drawing") for s in stats.values()) and sc["words"] < ocr_score.DRAWING_WORDS,
    }


def lib_fp(path):
    return Path(path).stem, sorted(dupcheck.library_fingerprint(str(path)))
