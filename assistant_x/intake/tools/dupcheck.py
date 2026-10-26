# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Content duplicate check: what share of a candidate's phrases already occurs in a library document.
Usage: python -m assistant_x.intake.tools.dupcheck <file.pdf | text.md | text.txt> [--pages N] [--top K]
Compares the first N pages (default 30) of the candidate with every index/texts/<code>.md.
Robust to file names, re-saves, a different scan or OCR, and Markdown vs plain text.
Fingerprints of library texts are cached in .assistant_x/fingerprints/<code>.fp and rebuilt when the text changes."""

import sys, os, re, glob, hashlib, subprocess, tempfile
from array import array

from assistant_x.core import lang, workspace
from assistant_x.core.formats import PAGE_WORDS

SHINGLE = 5  # words per phrase
SAMPLE = 16  # keep 1 of every SAMPLE phrase hashes (same rule for every document)
MIN_CHARS = 80
# share of the candidate's phrases found in a library text: another scan of the same book gives ~50 %,
# different books 0-2 %. From "auto" the intake (process.Batch.dup_verdict) marks a candidate a duplicate by itself
# (apply moves it to _duplicates) only when it is the same edition: "same" of the phrases, page counts within
# "pages_apart" of each other and no other year in the designation; another edition stays a suspect for Claude.
THRESHOLDS = {"partial": 0.08, "dup": 0.30, "auto": 0.60, "same": 0.90, "pages_apart": 0.10}
TESSERACT = os.environ.get("TESSERACT") or "tesseract"
MARK = re.compile(rf"(?:^|\n)=== (?:{PAGE_WORDS}) \d+ ===\n")
WORD_RX = re.compile(f"[{lang.chars('lower')}0-9]+")  # the letters of every active pack (folded: Russian yo as ye)


def texts_dir():
    """The library texts compared with: AX_TEXTS (the intake passes its own), else the texts of the workspace."""
    return os.environ.get("AX_TEXTS") or str(workspace.current().texts)


def cache_dir():
    """The fingerprint cache: AX_FP_CACHE (the intake passes its own), else the one of the workspace."""
    return os.environ.get("AX_FP_CACHE") or str(workspace.current().fingerprints)


def words(text):
    text = re.sub(r"<br>|<!--.*?-->|[*_#|]", " ", lang.fold(text.lower()))
    return [w for w in WORD_RX.findall(text) if len(w) >= 3]


def fingerprint(text):
    w = words(text)
    out = set()
    for i in range(len(w) - SHINGLE + 1):
        h = int.from_bytes(hashlib.blake2b(" ".join(w[i : i + SHINGLE]).encode(), digest_size=8).digest(), "little")
        if h % SAMPLE == 0:
            out.add(h >> 32)
    return out


def library_fingerprint(path, cache_folder=None):
    """The fingerprint of a library text, cached in cache_folder (default: cache_dir()) as <code>.fp: the sha256 of
    the text, then the hashes. The cache counts only for the same text: a renamed text (new codes after a base
    install keep the date of the file) never takes the fingerprint of the document that had its code before."""
    code = os.path.basename(path)[:-3]
    cache_folder = cache_folder or cache_dir()
    cache = os.path.join(cache_folder, f"{code}.fp")
    raw = open(path, "rb").read()
    digest = hashlib.sha256(raw).digest()
    if os.path.exists(cache):
        data = open(cache, "rb").read()
        if data[:32] == digest:
            a = array("I")
            a.frombytes(data[32:])
            return set(a)
    fp = fingerprint(raw.decode("utf-8"))
    os.makedirs(cache_folder, exist_ok=True)
    with open(cache + ".tmp", "wb") as f:
        f.write(digest + array("I", sorted(fp)).tobytes())
    os.replace(cache + ".tmp", cache)
    return fp


def verdict(share):
    if share >= THRESHOLDS["dup"]:
        return "DUPLICATE"
    if share >= THRESHOLDS["partial"]:
        return "partial match, check"
    return "no"


def ocr(page):
    import pymupdf

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        png = f.name
    page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY).save(png)
    try:
        # tessdata on the command line, not in the environment: Tesseract 5.5 fails on a non-ASCII TESSDATA_PREFIX
        env = dict(os.environ)
        data = env.pop("TESSDATA_PREFIX", None) or next(
            (
                d
                for d in [os.path.join(os.path.dirname(TESSERACT), "tessdata")]
                if os.path.dirname(TESSERACT) and os.path.isdir(d)
            ),
            None,
        )
        return subprocess.run(
            [TESSERACT, png, "-", *(["--tessdata-dir", data] if data else []), "-l", lang.tesseract(), "--psm", "3"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        ).stdout
    except subprocess.TimeoutExpired:
        return ""
    finally:
        os.unlink(png)


def candidate_text(path, pages):
    if path.lower().endswith(".pdf"):
        import pymupdf

        doc = pymupdf.open(path)
        texts = []
        for p in list(doc)[:pages]:
            t = p.get_text()
            texts.append(t if len(t.strip()) >= MIN_CHARS else ocr(p))
        return "\n".join(texts), doc.page_count
    parts = MARK.split(open(path, encoding="utf-8").read())
    return "\n".join(parts[1 : pages + 1] if len(parts) > 1 else parts), max(len(parts) - 1, 1)


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, d: int(args[args.index(k) + 1]) if k in args else d
    pages, top = opt("--pages", 30), opt("--top", 5)
    text, total = candidate_text(args[0], pages)
    cand = fingerprint(text)
    if len(cand) < 30:
        print(f"Too little text to compare ({len(cand)} phrases in the sample): check by the title and the contents.")
        sys.exit(2)
    me = os.path.abspath(args[0])
    res = []
    for f in sorted(glob.glob(os.path.join(texts_dir(), "[!_]*.md"))):
        if os.path.abspath(f) == me:
            continue
        res.append((len(cand & library_fingerprint(f)) / len(cand), os.path.basename(f)[:-3]))
    res.sort(reverse=True)
    print(
        f"Candidate: {os.path.basename(args[0])}, pages in all {total}, compared {min(pages, total)}, phrases in the sample {len(cand)}"
    )
    for share, code in res[:top]:
        print(f"  {code}: {share:.0%} of the phrases found — {verdict(share)}")
    print(
        "Threshold: from 30 % a duplicate (another scan of the same book gives about 50 %); 8–30 % a partial match, "
        "look by hand; from 60 % the background intake moves the file to _duplicates by itself when it is the same "
        "edition (90 % of the phrases, the same page count and designation)."
    )
