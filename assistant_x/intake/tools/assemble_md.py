# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble texts/<code>.md from converted Markdown pages, falling back to the old page text
where the conversion lost text or came out garbled. A cache file that does not read (broken JSON) counts as missing:
it is removed with a warning, so the next run converts those pages again.
The text is written in the text format "AX text 1" (core/formats.py, docs/INTAKE.md): UTF-8, LF, NFC, no invisible
characters, a line of a body that reads as a page marker escaped. The two characters the OCR font shares a glyph with
are fixed on every page (ocr_page.FONT_FIX); on an OCR page a word broken at the end of a line is joined when the
vocabulary of the library knows the whole word (common.dehyphenate).
Beside it <code>.pages.json, every page with
  source     layer (the page was not converted: the plain text layer), markdown, ocr (converted, recognised by OCR),
             fallback (the conversion was refused, the text layer taken instead)
  ocr_score  the recognition score 0-100 of the page (tools/ocr_score.py, with the Tesseract confidence of an OCR page)
  label      the printed page label of the PDF (its page labels, when it has them), else null
  flags      "complex_table": a Markdown table with a row of another cell count than its header (merged cells);
             "formula": a line ending with an equation number (core/textmap.py)
Usage: python -m assistant_x.intake.tools.assemble_md <old_text_dir> <cache_dir> <out_dir> [--jobs JOBS] [CODE ...]
JOBS: the jobs.json of convert_md; the labels come from the "label_pdf" of a job, else from the PDFs of its parts.
(a persistent worker of intake.py calls main(argv) in its own process)"""

import sys, os, re, glob, json, unicodedata

from assistant_x.core import lang
from assistant_x.core.common import INVISIBLE_RX as INVISIBLE, dehyphenate  # the characters a reader does not see
from assistant_x.core.formats import PAGE_WORDS, PAGES_SUFFIX, escape_marker, unescape_text, write_pages_info
from assistant_x.intake.tools import ocr_page, ocr_score
from assistant_x.intake.tools.convert_md import kept, words
from assistant_x.core.textmap import has_formula

MARK = re.compile(rf"^=== (?:{PAGE_WORDS}) (\d+) ===$", re.M)
LETTER_RX = re.compile(f"[{lang.chars('lower')}]")  # the letters of every active pack, by the lower case
# the packs whose letters a broken font encoding or a bad recognition turns into Latin (keep_share): a converted page
# must keep about the share of them its text layer has
KEEP_RX = {code: re.compile(f"[{cls}]") for code, cls in lang.letters("lower").items() if lang.get(code, "keep_share")}


def plain(s):
    """Text without Markdown/HTML markup, so tags and Greek symbols don't count as foreign letters."""
    s = re.sub(r"<!--.*?-->|</?[a-z]+>", " ", s)
    return [c for c in s if c.isalpha() and LETTER_RX.match(c.lower())]


def kept_shares(s):
    """{code: share of the letters of the keep_share pack among the letters of the text}."""
    letters = plain(s)
    return {
        code: sum(bool(rx.match(c.lower())) for c in letters) / len(letters) if letters else 0.0
        for code, rx in KEEP_RX.items()
    }


def keeps_letters(m, o):
    """True when the converted page m keeps the letters of the text layer o (within 5 points, 80 % at most asked)."""
    sm, so = kept_shares(m), kept_shares(o)
    return all(sm[c] >= min(0.8, so[c]) - 0.05 for c in KEEP_RX)


def letters(s):
    return len(plain(s))


def read_pages(path):
    """{page: body} of the plain text of the text layer (work.prep writes it with the markers of the text format)."""
    parts = MARK.split(open(path, encoding="utf-8").read())
    return {int(parts[i]): unescape_text(parts[i + 1].strip("\n")) for i in range(1, len(parts), 2)}


def tidy(md):
    md = re.sub(r"</?mark>", "", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip("\n")


def ocr_stats(cache, code):
    """{page: the OCR measures of convert_md} of the pages of a document recognised by OCR."""
    out = {}
    for f in sorted(glob.glob(f"{cache}/{code}/ocr/*.json")):  # z_force_* (empty pages read again) come last
        try:
            with open(f, encoding="utf-8") as fh:
                out.update({int(k): v for k, v in json.load(fh).items()})
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return out


def labels(job):
    """{page: printed label} from the PDF of a job; {} when it has no page labels or does not open."""
    import pymupdf

    parts = [[job["label_pdf"], 1]] if job.get("label_pdf") else job.get("parts") or []
    out = {}
    for path, first in parts:
        try:
            with pymupdf.open(path) as doc:
                if doc.get_page_labels():
                    out.update({first + i: page.get_label() or None for i, page in enumerate(doc)})
        except Exception as e:  # noqa: BLE001 — a text without labels is still a text
            print(f"WARNING {path}: the page labels were not read ({e!r})", file=sys.stderr, flush=True)
    return out


def complex_table(text):
    """True when a Markdown table of the text has a row with another number of cells than its header (merged cells)."""
    head = None
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            head = None
            continue
        n = len(s.strip("|").split("|"))
        if head is None:
            head = n
        elif n != head:
            return True
    return False


def page_flags(text):
    return [f for f, on in (("complex_table", complex_table(text)), ("formula", has_formula(text))) if on]


def main(argv):
    argv, jobs = list(argv), {}
    if "--jobs" in argv:
        i = argv.index("--jobs")
        with open(argv[i + 1], encoding="utf-8") as f:
            jobs = json.load(f)
        del argv[i : i + 2]
    old_dir, cache, out_dir, codes = argv[0], argv[1], argv[2], argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    codes = codes or sorted(os.path.basename(p)[:-4] for p in glob.glob(f"{old_dir}/*.txt"))
    report = {}
    for code in codes:
        old = read_pages(f"{old_dir}/{code}.txt")
        new = {}
        for f in sorted(glob.glob(f"{cache}/{code}/*.json")):  # z_force_* re-OCR files override
            try:
                with open(f, encoding="utf-8") as fh:
                    pages = {int(k): tidy(v) for k, v in json.load(fh).items()}
            except (ValueError, AttributeError, TypeError) as e:
                print(
                    f"WARNING {f}: a broken cache was deleted, these pages come from the fallback text ({e!r})",
                    file=sys.stderr,
                    flush=True,
                )
                os.remove(f)
                continue
            new.update(pages)
        stats, labs = ocr_stats(cache, code), labels(jobs.get(code) or {})
        known = ocr_score.load_vocab()[0] if stats else None
        used, fallback, out, invisible, info = 0, [], [], 0, {}
        for n in sorted(set(old) | set(new)):
            o, m = old.get(n, ""), new.get(n)
            # a broken font encoding shows up as U+FFFD; such pages are garbled even if the letters look fine
            if (
                m is not None
                and letters(m) >= 0.7 * letters(o)
                and keeps_letters(m, o)
                and m.count("\ufffd") <= 0.1 * letters(m)
            ):
                body, used, source = m, used + 1, "ocr" if n in stats else "markdown"
                if source == "ocr" and words(o) and kept(words(o), words(m)) < ocr_page.LOST_SHARE:
                    body = m + "\n\n" + o  # the text layer of a scan (a stamp, a header) OCR did not read: kept after it
            else:
                body, source = o, "layer" if m is None else "fallback"
                if m is not None and letters(o) > 0:
                    fallback.append(n)
            body, k = INVISIBLE.subn("", body.translate(ocr_page.FONT_FIX))
            invisible += k
            body = unicodedata.normalize("NFC", body)
            if source == "ocr":
                body = dehyphenate(body, known)
            out.append(f"=== page {n} ===\n\n{escape_marker(body)}\n")
            info[n] = {"source": source, "ocr_score": None, "label": labs.get(n), "flags": page_flags(body)}
        text = "\n".join(out)
        with open(f"{out_dir}/{code}.md", "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        for p in ocr_score.score_text(text, stats)["pages"] if out else []:
            if p["page"] in info:
                info[p["page"]]["ocr_score"] = p["score"]
        write_pages_info(f"{out_dir}/{code}{PAGES_SUFFIX}", info)
        report[code] = {
            "pages": len(out),
            "markdown": used,
            "old_text": len(fallback),
            "tables": sum(new[n].count("|---") for n in new),
            "fallback_pages": fallback[:15],
            "invisible_chars": invisible,
        }
        print(code, json.dumps(report[code], ensure_ascii=False), flush=True)
    with open(f"{out_dir}/_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
