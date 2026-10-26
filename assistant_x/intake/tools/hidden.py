# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find text in a PDF that a reader does not see but text extraction picks up (a way to plant instructions
for Claude): white or near-white text on a light background, text in a tiny font, transparent text,
invisible text (render mode 3) on a page that is not a scan, text outside the page.
The invisible OCR layer of a scanned page is normal and is not counted.
Usage: python -m assistant_x.intake.tools.hidden <file.pdf> [--clean <out.pdf>] [--json <report.json>]
  --clean: copy of the PDF with the hidden text removed, written only if some was found
           (convert that copy instead of the original).
Prints one line per hidden fragment and a summary; the report lists page, reason and text."""

import sys, json
import pymupdf as fitz

TINY = 2.0  # pt: smaller text is not readable on paper
LIGHT = 0.75  # text this light (0..1) is checked against what is under it
FLAT = 25  # grey levels: a text box rendered this flat shows nothing to the reader
SCAN = 0.6  # share of the page under images: such a page is a scan and its invisible text is OCR
SHIFTED = 0.3  # share of the spans of a page outside the page box from which its text layer is shifted, not hidden
SHIFTED_WHY = "text layer shifted off the page box"
MAX_SPANS = 200  # spans written to the report at most (the count stays whole)


def luminance(c):
    if not c:
        return 0.0
    c = (c * 3)[:3] if len(c) == 1 else c[:3]
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def scan_page(page):
    area = abs(page.rect)
    covered = sum(abs(fitz.Rect(i["bbox"]) & page.rect) for i in page.get_image_info())
    return area > 0 and covered / area >= SCAN


def looks_flat(page, rect):
    """True when the text box, rendered with the text in it, is one flat colour: the text is not visible."""
    pix = page.get_pixmap(clip=rect, dpi=96, colorspace=fitz.csGRAY)
    s = pix.samples
    return len(s) > 0 and max(s) - min(s) < FLAT


def check(page):
    """[(reason, text, rect)] of the hidden text on the page."""
    out, scan = [], None
    for s in page.get_texttrace():
        text = "".join(chr(c[0]) for c in s["chars"]).strip()
        if not text:
            continue
        r = fitz.Rect(s["bbox"])
        why = None
        if not r.intersects(page.rect):
            why = "outside the page margins"
        elif s.get("opacity", 1) < 0.1:
            why = "transparent text"
        elif s["type"] == 3:
            scan = scan_page(page) if scan is None else scan
            if not scan:
                why = "invisible text (mode 3) not on a scan"
        elif s["size"] < TINY:
            why = f"font {s['size']:.1f} pt"
        elif luminance(s["color"]) >= LIGHT and looks_flat(page, r & page.rect):
            why = "text blends with the background"
        if why:
            out.append((why, text, r))
    return out


def shifted(page, hits):
    """(the hits that stay hidden, the summary of a shifted text layer or None): when more than SHIFTED of the spans of
    a page lie outside the page box, the text layer sits off its CropBox (audit 6, M-007): one line for the page
    instead of a line per word, and it is no hidden text."""
    spans = sum(1 for s in page.get_texttrace() if "".join(chr(c[0]) for c in s["chars"]).strip())
    outside = [h for h in hits if h[0] == "outside the page margins"]
    if not spans or len(outside) <= SHIFTED * spans:
        return hits, None
    sample = " ".join(t for _, t, _ in outside[:12])[:300]
    return [h for h in hits if h[0] != "outside the page margins"], {
        "why": SHIFTED_WHY,
        "spans": len(outside),
        "text": sample,
    }


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    src, clean, rep = argv[0], None, None
    if "--clean" in argv:
        clean = argv[argv.index("--clean") + 1]
    if "--json" in argv:
        rep = argv[argv.index("--json") + 1]
    doc = fitz.open(src)
    found, layer = {}, {}
    for page in doc:
        try:
            hits = check(page)
        except Exception as e:  # a damaged page: say so and go on
            print(f"page {page.number + 1}: not checked ({e!r})")
            continue
        if not hits:
            continue
        hits, moved = shifted(page, hits)
        if moved:
            layer[page.number + 1] = moved
            print(f"page {page.number + 1}: {SHIFTED_WHY} ({moved['spans']} spans)")
        if not hits:
            continue
        found[page.number + 1] = [{"why": w, "text": t[:300]} for w, t, _ in hits]
        for w, t, _ in hits:
            print(f"page {page.number + 1}: {w}: {t[:120]}")
        if clean:
            for w, t, r in hits:
                if r.intersects(page.rect):  # text outside the page is not extracted anyway
                    page.add_redact_annot(r, fill=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    n = sum(len(v) for v in found.values())
    kept, left = {}, MAX_SPANS
    for p in sorted(found):  # the report keeps the first MAX_SPANS spans; "hidden" counts them all
        if left <= 0:
            break
        kept[p], left = found[p][:left], left - len(found[p][:left])
    summary = {"file": src, "pages": doc.page_count, "hidden": n, "hidden_pages": sorted(found), "found": kept}
    if layer:
        summary["shifted_pages"] = sorted(layer)
        summary["shifted"] = {str(p): v for p, v in sorted(layer.items())}
    if clean and n:  # nothing hidden: convert the original, no copy needed
        doc.save(clean, garbage=3, deflate=True)
        summary["clean"] = clean
    if rep:
        json.dump(summary, open(rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"hidden fragments: {n}" + (f" on pages {', '.join(map(str, sorted(found)[:20]))}" if n else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
