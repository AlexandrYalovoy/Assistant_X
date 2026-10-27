# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""OCR of one page for pymupdf4llm (its ocr_function) through the Tesseract program, so that the word confidence
comes with the text in the same run (the Tesseract built into PyMuPDF gives none).

exec_ocr(page, dpi, language, keep_ocr_text): like pymupdf4llm.ocr.tesseract_api.exec_ocr, the page is drawn without
its legible text, recognised in the languages given (by default the document languages: core/lang.tesseract();
tesseract --oem 1 … tsv txt: the LSTM engine, as in PyMuPDF) and the words are put on the page as
invisible text, each in its own box. The orientation of every such page is checked (psm 0, OSD, on a half-size copy): turned
by 90/180/270 with confidence of at least OSD_CONF, the turned image is recognised too. The page is scored
(tools/ocr_score.py: unknown words and confidence); a weak page (mean confidence below QUALITY["ocr_retry_conf"] or
more than QUALITY["ocr_retry_nonword"] unknown words) is recognised again at 400 dpi and binarised. The variant with
the best score is kept (a turned one unless it is much worse). A turned page keeps the plain text of the turned
image: convert_md takes OVERRIDE[page] instead of the Markdown of the page.

STATS[page number from 0] = {conf, low, words, bad, score, variant, rotate, tried: {variant: score}, seconds}
reset() before each document (or chunk of pages).

A page with a legible text layer of MIN_WORDS words or more (a scan the publisher gave a visible text, a text page
with a picture) is read once (no orientation check, no retries): when LAYER_KEEP of the distinct recognised words are
already in the layer, the recognition is dropped (STATS "layer": "kept"); else only the recognised words the layer does
not have are put on the page (a figure caption, a stamp: "layer": "added"). The layer is often shifted from the glyphs
under it, so the blanked image still shows them: an invisible copy of the whole page would double every phrase.
A page prep does not count as a scan (SCAN_PAGES, set by convert_md for each document: a text page with a picture)
gets the same single reading in the sparse text mode (psm 11), kept only when it adds MIN_WORDS words the layer
lacks: the labels of a figure, not a second copy of the text.

Speed, the outputs unchanged: the orientation is checked on the first OSD_SAMPLE pages of a document; when they agree,
the other pages take it (a page whose first reading is weak is checked again itself). The retry of weak pages is chosen
per document: after RETRY_SAMPLE weak pages, a retry variant (400 dpi or black and white) that won RETRY_SHARE of them
is the only one tried on the rest. prerecognise() reads the pages of a chunk in one Tesseract process (a list of
images): exec_ocr takes such a reading when the image of the page is the same, else it runs Tesseract on the page.
"""

import os, re, shutil, tempfile, time, unicodedata

from assistant_x.core import proc

from assistant_x.core import lang
from assistant_x.intake.tools import ocr_score
from assistant_x.intake.tools.ocr_score import QUALITY

OSD_CONF = 2.0  # orientation confidence of Tesseract that a turn is trusted at
RETRY_DPI = 400
MIN_WORDS = 8  # a page with fewer recognised words is not tried again (a stamp, a page number)
LOST_SHARE = 0.6  # the Markdown of a page keeps less than this share of the recognised words: take the plain text
OSD_SAMPLE = 5  # pages of a document whose orientation is checked each; the others take theirs when they agree
RETRY_SAMPLE, RETRY_SHARE = 10, 0.7  # weak pages after which a retry variant that won this share is the only one tried
LAYER_KEEP = 0.7  # share of the recognised words already in the legible layer from which the recognition is dropped
WORD_RX = re.compile(r"[^\W_]+")
STATS, OVERRIDE, PLAIN = {}, {}, {}
SCAN_PAGES = None  # the pages (from 0) of the document prep counts as scans; None: not known, every page is one
DOCS = {}  # document -> {"osd": [(rotate, confidence)], "wins": [retry variant that won]}: kept between chunks
PRE = {}  # page number from 0 -> (the PNG of the page, its reading by prerecognise)
_tess = None


def reset():
    STATS.clear()
    OVERRIDE.clear()
    PLAIN.clear()
    PRE.clear()


def doc_state(name):
    """What is known of a document across its chunks (orientation sample, retry winners); a few documents kept."""
    if name not in DOCS and len(DOCS) >= 8:
        DOCS.pop(next(iter(DOCS)))
    return DOCS.setdefault(name, {"osd": [], "wins": []})


def sampled_turn(state):
    """(rotate, confidence) the sample of a document agrees on, or None while it is short or disagrees."""
    osd = state["osd"]
    if len(osd) < OSD_SAMPLE or len({r for r, _ in osd}) != 1:
        return None
    return osd[0][0], min(c for _, c in osd)


def retry_choice(state):
    """The retry variant ("dpi" or "bw") to try alone on a weak page, or None: both are tried."""
    wins = [w for w in state["wins"] if w]
    if len(state["wins"]) < RETRY_SAMPLE:
        return None
    for kind in ("dpi", "bw"):
        if wins.count(kind) >= RETRY_SHARE * len(state["wins"]):
            return kind
    return None


def win_kind(key):
    return "dpi" if key.startswith(str(RETRY_DPI)) else "bw" if key.startswith("b/w") else ""


def tesseract_exe():
    """Path of the Tesseract program (TESSERACT from intake_cfg.tool_env, else PATH), or None."""
    global _tess
    if _tess is None:
        _tess = os.environ.get("TESSERACT") or shutil.which("tesseract") or ""
        if _tess and not os.path.isfile(_tess):
            _tess = shutil.which(_tess) or ""
    return _tess or None


def tessdata_args(env):
    """TESSDATA_PREFIX taken out of env and given as --tessdata-dir: Tesseract 5.5 stops with «filesystem error: Cannot
    convert character sequence» on a non-ASCII tessdata path found from the environment or beside its program
    (a project folder with non-ASCII characters); the same path on the command line it reads. No TESSDATA_PREFIX: the
    tessdata beside the program."""
    d = env.pop("TESSDATA_PREFIX", None)
    if not d and tesseract_exe():
        beside = os.path.join(os.path.dirname(tesseract_exe()), "tessdata")
        d = beside if os.path.isdir(beside) else None
    return ["--tessdata-dir", d] if d else []


def _run(args, timeout=600):
    env = dict(os.environ, OMP_THREAD_LIMIT=os.environ.get("OMP_THREAD_LIMIT", "1"))
    args = [*args[:2], *tessdata_args(env), *args[2:]]  # image, output base, then the options
    # CREATE_NO_WINDOW and the priority class of assistant_x.toml (AX_PRIORITY, balance.py); the CPUs come from the worker's job
    prio = {"below_normal": 0x4000, "idle": 0x40}.get(os.environ.get("AX_PRIORITY", ""), 0)
    kw = {"creationflags": 0x08000000 | prio} if os.name == "nt" else {}
    return proc.run([tesseract_exe(), *args], capture_output=True, timeout=timeout, env=env, **kw)


def parse_tsv(text):
    """(plain text by lines, [confidence of every word], [(left, top, width, height, word, line)]) from the tsv
    output of Tesseract (pixels of the image)."""
    lines, confs, words, key, cur = [], [], [], None, []
    for row in text.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        word = c[11].strip()
        try:
            conf = float(c[10])
            box = tuple(int(x) for x in c[6:10])
        except ValueError:
            continue
        if not word or conf < 0:
            continue
        k = (c[2], c[3], c[4])
        if k != key and cur:
            lines.append(" ".join(cur))
            cur = []
        key = k
        cur.append(word)
        confs.append(conf)
        words.append((*box, word, k))
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines), confs, words


_font = None
# Arial gives one glyph to two characters; the text read back from the page takes the other one (assemble_md applies it
# to every page: a soft hyphen or a Latin letter middle dot in a text layer reads the same)
FONT_FIX = str.maketrans({"\u00ad": "-", "\ua78f": "\u00b7"})


def ocr_font():
    """(name, file or None, pymupdf.Font) of the invisible text: Arial has Cyrillic, Greek and the usual signs."""
    global _font
    if _font is None:
        import pymupdf

        f = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arial.ttf")
        _font = ("atocr", f, pymupdf.Font(fontfile=f)) if os.path.isfile(f) else ("atocr", None, pymupdf.Font("cjk"))
    return _font


def insert_words(page, words, width, height):
    """Put the recognised words on the page as invisible text, each in its own box: the gaps between words stay
    real gaps, so the table analysis of pymupdf4llm keeps the spaces (the text layer of the Tesseract PDF loses
    them in table cells: two words run together)."""
    import pymupdf

    if not words:
        return
    name, file, font = ocr_font()
    if file:
        page.insert_font(fontname=name, fontfile=file)
    else:
        page.insert_font(fontname=name, fontbuffer=font.buffer)
    sx, sy = page.rect.width / width, page.rect.height / height
    by_line = {}
    for w in words:
        by_line.setdefault(w[5], []).append(w)
    for line in by_line.values():
        top = min(w[1] for w in line) * sy
        bottom = max(w[1] + w[3] for w in line) * sy
        size = max(bottom - top, 1.0)
        for left, _, w_px, _, word, _ in line:
            pos = pymupdf.Point(left * sx, bottom - 0.2 * size)
            length = font.text_length(word, fontsize=size)
            mat = pymupdf.Matrix(w_px * sx / length, 1) if length > 0 else pymupdf.Matrix(1, 1)
            page.insert_text(pos, word, fontsize=size, fontname=name, render_mode=3, morph=(pos, mat))


def measure(text, confs):
    """Score of a recognised text with the confidence of its words."""
    n, bad, _ = ocr_score.word_counts(text)
    if not confs:
        return {"tokens": 0, "words": n, "bad": bad, "conf": None, "low": None, "score": ocr_score.page_score(n, bad)}
    mean = sum(confs) / len(confs)
    low = sum(c < QUALITY["ocr_low_conf"] for c in confs) / len(confs)
    return {
        "tokens": len(confs),
        "words": n,
        "bad": bad,
        "conf": round(mean, 1),
        "low": round(low, 3),
        "score": ocr_score.page_score(n, bad, mean, low),
    }


def weak(m):
    if m["tokens"] < MIN_WORDS:
        return False
    if m["conf"] is not None and m["conf"] < QUALITY["ocr_retry_conf"]:
        return True
    return bool(m["words"]) and m["bad"] / m["words"] > QUALITY["ocr_retry_nonword"]


def split_tsv(text):
    """{page_num: tsv text with the header} of the tsv Tesseract writes for a list of images."""
    lines = text.splitlines()
    out = {}
    for row in lines[1:]:
        c = row.split("\t")
        if len(c) >= 12 and c[1].isdigit():
            out.setdefault(int(c[1]), [lines[0]]).append(row)
    return {k: "\n".join(v) for k, v in out.items()}


def prerecognise(items, dpi, language):
    """Read [(page number from 0, PNG path)] in one Tesseract process (a list of images): PRE[page] = (PNG bytes,
    recognise()-like reading). Nothing is kept when the output does not split into the pages (exec_ocr then reads the
    pages one by one)."""
    import pymupdf

    if len(items) < 2 or not tesseract_exe():
        return 0
    tmp = tempfile.mkdtemp(prefix="ax_ocrb_")
    try:
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.write("\n".join(p for _, p in items) + "\n")
        base = os.path.join(tmp, "all")
        r = _run([lst, base, "-l", language, "--oem", "1", "--dpi", str(dpi), "tsv", "txt"], timeout=600 + 120 * len(items))
        if r.returncode != 0 or not os.path.exists(base + ".tsv") or not os.path.exists(base + ".txt"):
            return 0
        with open(base + ".tsv", encoding="utf-8", errors="replace") as f:
            pages = split_tsv(f.read())
        with open(base + ".txt", encoding="utf-8", errors="replace") as f:
            plains = f.read().split("\f")
        if len(plains) < len(items):
            return 0
        for k, (no, png) in enumerate(items):
            text, confs, words = parse_tsv(pages.get(k + 1, ""))
            img = pymupdf.Pixmap(png)
            with open(png, "rb") as f:
                PRE[no] = (
                    f.read(),
                    {
                        "words": words,
                        "size": (img.width, img.height),
                        "text": text,
                        "plain": plains[k],
                        "m": measure(text, confs),
                    },
                )
        return len(items)
    finally:
        _clean(tmp)


def norm_words(text):
    """The words of a text as the layer and the recognition are compared: lower case, NFC, letters and digits only."""
    return WORD_RX.findall(unicodedata.normalize("NFC", text.lower()))


def page_image(page, dpi):
    """(gray Pixmap of the page without its legible text, its legible spans, empty, has OCR text, display list, the
    normalised words of the legible spans) as exec_ocr reads it."""
    import pymupdf
    from pymupdf4llm.ocr.get_culled_pixmap import get_pixmap
    from pymupdf4llm.ocr.tesseract_api import ocr_text

    displaylist = page.get_displaylist()
    stext = pymupdf.TextPage(displaylist.get_textpage(flags=pymupdf.TEXT_ACCURATE_BBOXES))
    spans, ocr_spans, layer = [], [], []
    for b in stext.extractDICT()["blocks"]:
        for ln in b["lines"]:
            for s in ln["spans"]:
                if ocr_text(s):
                    ocr_spans.append(s["bbox"])
                elif "\ufffd" not in s["text"]:
                    spans.append(s["bbox"])
                    layer += norm_words(s["text"])
    pix, empty = get_pixmap(displaylist, dpi=dpi, rects=spans, empty_threshold=250)
    return pix, spans, empty, bool(ocr_spans), displaylist, layer


def recognise(png, dpi, language, tmp, tag, psm=None):
    """Run Tesseract on a PNG: {'words': boxes of the words, 'size': (width, height) of the image, 'text', 'plain',
    'm': measure()}. psm 11: sparse text (a drawing sheet: labels all over the sheet, no columns)."""
    import pymupdf

    base = os.path.join(tmp, tag)
    r = _run(
        [png, base, "-l", language, "--oem", "1", "--dpi", str(dpi), *(["--psm", str(psm)] if psm else []), "tsv", "txt"]
    )
    if r.returncode != 0 or not os.path.exists(base + ".tsv"):
        raise RuntimeError(f"tesseract {tag}: code {r.returncode}: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    with open(base + ".tsv", encoding="utf-8", errors="replace") as f:
        text, confs, words = parse_tsv(f.read())
    with open(base + ".txt", encoding="utf-8", errors="replace") as f:
        plain = f.read()
    img = pymupdf.Pixmap(png)
    return {"words": words, "size": (img.width, img.height), "text": text, "plain": plain, "m": measure(text, confs)}


def orientation(png, tmp, dpi=150):
    """(degrees to turn the image clockwise, confidence) from Tesseract OSD, or (0, 0) when it cannot tell."""
    r = _run([png, os.path.join(tmp, "osd"), "--psm", "0", "--dpi", str(dpi)], timeout=120)
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    try:
        with open(os.path.join(tmp, "osd.osd"), encoding="utf-8", errors="replace") as f:
            out += f.read()
    except OSError:
        pass
    rot = re.search(r"Rotate:\s*(\d+)", out)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
    return (int(rot.group(1)) % 360 if rot else 0), (float(conf.group(1)) if conf else 0.0)


def gray(pix):
    import pymupdf

    return pix if pix.n == 1 and not pix.alpha else pymupdf.Pixmap(pymupdf.csGRAY, pix)


def save_array(arr, path):
    import pymupdf

    h, w = arr.shape
    pymupdf.Pixmap(pymupdf.csGRAY, w, h, arr.tobytes(), 0).save(path)


def _array(pix):
    import numpy as np

    g = gray(pix)
    return np.frombuffer(g.samples, dtype=np.uint8).reshape(g.height, g.stride)[:, : g.width]


def choose(tried, rotate):
    """Key of the best variant. When Tesseract sees the page turned, a turned variant wins unless it scores
    10 points less: the upright reading of a sideways page loses its text in the layout analysis."""
    score = {k: v["m"]["score"] or 0 for k, v in tried.items()}
    best = max(score, key=lambda k: (score[k], k == next(iter(tried))))
    turned = [k for k in score if "rotate" in k]
    if rotate and turned:
        t = max(turned, key=score.get)
        if score[t] >= score[best] - 10:
            return t
    return best


def binarise(pix, path, rotate=0):
    """Black and white by Otsu's threshold (turned clockwise by rotate)."""
    import numpy as np

    a = _array(pix)
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    w = np.cumsum(hist)
    mu = np.cumsum(hist * np.arange(256))
    total, mt = w[-1], mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w - mu * total) ** 2 / (w * (total - w))
    t = int(np.nanargmax(between[:-1]))
    save_array(np.ascontiguousarray(np.rot90(np.where(a > t, 255, 0).astype(np.uint8), k=-(rotate // 90))), path)


def turn(pix, degrees, path):
    """The page image turned clockwise."""
    import numpy as np

    save_array(np.ascontiguousarray(np.rot90(_array(pix), k=-(degrees // 90))), path)


def _clean(tmp):
    for f in os.listdir(tmp):
        try:
            os.remove(os.path.join(tmp, f))
        except OSError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass


def new_words(words, layer):
    """The recognised words (boxes of parse_tsv) the legible layer does not have."""
    return [w for w in words if not set(norm_words(w[4])) <= layer]


def beside_layer(page, png, dpi, language, tmp, layer, psm=None, t0=None, min_new=1):
    """One reading of a page with a legible layer (or a picture on a text page): dropped when the layer already has
    LAYER_KEEP of its distinct words or the reading adds fewer than min_new words, else only the words the layer
    lacks are put on the page."""
    pre = PRE.pop(page.number, None)
    with open(png, "rb") as f:
        same = pre is not None and pre[0] == f.read()
    best = pre[1] if same else recognise(png, dpi, language, tmp, "v0", psm=psm)
    seen = set(norm_words(best["text"]))
    share = len(seen & layer) / len(seen) if seen else 1.0
    st = {"tokens": best["m"]["tokens"], "layer_share": round(share, 2)}
    add = new_words(best["words"], layer) if share < LAYER_KEEP else []
    if len(add) < min_new:
        st["layer"] = "kept"
    else:
        insert_words(page, add, *best["size"])
        lines = {}
        for w in add:
            lines.setdefault(w[5], []).append(w[4])
        PLAIN[page.number] = ("\n".join(" ".join(x) for x in lines.values()), False)
        st.update(layer="added", added=len(add), conf=best["m"]["conf"], low=best["m"]["low"])
    seconds = round(time.time() - t0, 1) if t0 else 0.0
    STATS[page.number] = {**st, "variant": f"layer psm {psm}" if psm else "layer", "rotate": 0, "seconds": seconds}
    return STATS[page.number]


def exec_ocr(page, dpi=300, pixmap=None, language=None, keep_ocr_text=False):
    import pymupdf

    language = language or lang.tesseract()
    from pymupdf4llm.ocr.get_culled_pixmap import get_pixmap

    t0 = time.time()
    pix, spans, empty, has_ocr, displaylist, layer = page_image(page, dpi)
    if has_ocr and keep_ocr_text:
        return
    if empty:
        return
    state = doc_state(page.parent.name)
    tmp = tempfile.mkdtemp(prefix="ax_ocr_")
    try:
        png = os.path.join(tmp, "p.png")
        g = gray(pix)
        g.save(png)
        dpi = round(pix.width / page.rect.width * 72)  # get_pixmap lowers the dpi of a big page (a drawing sheet)
        drawing = ocr_score.is_drawing(page.parent.page_count, page.rect.width * page.rect.height)
        picture = SCAN_PAGES is not None and page.number not in SCAN_PAGES  # a text page with a picture
        if len(layer) >= MIN_WORDS or picture:
            psm = 11 if drawing or picture else None
            beside_layer(page, png, dpi, language, tmp, set(layer), psm, t0, MIN_WORDS if picture else 1)
            return
        if drawing:
            # a drawing gets one sparse-text pass; turning and retrying did not raise its score (177 of 288 in redo)
            best = recognise(png, dpi, language, tmp, "v0", psm=11)
            PLAIN[page.number] = (best["plain"].strip(), not spans)
            insert_words(page, best["words"], *best["size"])
            STATS[page.number] = {
                **best["m"],
                "variant": "drawing psm 11",
                "rotate": 0,
                "drawing": True,
                "tried": {"drawing psm 11": best["m"]["score"]},
                "seconds": round(time.time() - t0, 1),
            }
            return
        pre = PRE.pop(page.number, None)
        with open(png, "rb") as f:
            same = pre is not None and pre[0] == f.read()
        tried = {str(dpi): pre[1] if same else recognise(png, dpi, language, tmp, "v0")}
        # orientation on a half-size copy (0.5 s instead of 1 s); a page read sideways may still score well,
        # but its text runs vertically and the layout analysis drops it. The first pages of a document are checked
        # each; when they agree, the others take their orientation unless the first reading of the page is weak
        sample = sampled_turn(state)
        if sample and not weak(tried[str(dpi)]["m"]):
            rotate, rconf = sample
        else:
            half = pymupdf.Pixmap(g)
            half.shrink(1)
            half.save(os.path.join(tmp, "h.png"))
            rotate, rconf = orientation(os.path.join(tmp, "h.png"), tmp, dpi // 2)
            if rotate not in (90, 180, 270) or rconf < OSD_CONF:
                rotate = 0
            if len(state["osd"]) < OSD_SAMPLE:
                state["osd"].append((rotate, rconf))
        if rotate:
            turn(pix, rotate, os.path.join(tmp, "r.png"))
            tried[f"rotate {rotate}"] = recognise(os.path.join(tmp, "r.png"), dpi, language, tmp, "v1")
        key = choose(tried, rotate)
        if weak(tried[key]["m"]):
            turned = key.startswith("rotate")
            tag = f" rotate {rotate}" if turned else ""
            only = retry_choice(state)  # the variant that won most weak pages of the document so far
            if only != "bw":
                big, _ = get_pixmap(displaylist, dpi=RETRY_DPI, rects=spans, empty_threshold=250)
                big_dpi = round(big.width / page.rect.width * 72)  # get_pixmap lowers the dpi of a big page
                b = os.path.join(tmp, "b.png")
                if turned:
                    turn(big, rotate, b)
                else:
                    gray(big).save(b)
                tried[f"{RETRY_DPI}{tag}"] = recognise(b, big_dpi, language, tmp, "v2")
            if only != "dpi":
                k = os.path.join(tmp, "k.png")
                binarise(pix, k, rotate if turned else 0)
                tried[f"b/w{tag}"] = recognise(k, dpi, language, tmp, "v3")
            key = choose(tried, rotate)
            state["wins"].append(win_kind(key))
        best = tried[key]
        if "rotate" in key:
            OVERRIDE[page.number] = best["plain"].strip()
        else:
            # convert_md checks the layout analysis kept the recognised words (True: the whole page was recognised)
            PLAIN[page.number] = (best["plain"].strip(), not spans)
            insert_words(page, best["words"], *best["size"])
        STATS[page.number] = {
            **best["m"],
            "variant": key,
            "rotate": rotate if "rotate" in key else 0,
            "osd": [rotate, rconf],
            "tried": {k: v["m"]["score"] for k, v in tried.items()},
            "seconds": round(time.time() - t0, 1),
        }
    finally:
        _clean(tmp)
