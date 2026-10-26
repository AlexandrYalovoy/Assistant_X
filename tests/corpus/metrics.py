# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quality of the intake on the golden corpus (documents.py), as numbers:

    phrase_recall      share of the expected phrases found on their pages
    heading_recall     share of the expected headings in the outline; heading_precision: share of the outline expected
    ocr_accuracy       character accuracy of the text of the scanned pages against the text rendered (difflib ratio)
    verdict_accuracy   share of the duplicate verdicts (dup, suspect, none) as expected
    meta_accuracy      share of the genres, designations and drawing marks as expected

Two modes. fast: the text layer of the PDFs as prep reads it, the outline (core/textmap with the bookmarks or the
heading styles of the file), the draft (metadraft) and the duplicate check (process.Batch) — no Tesseract, no
LibreOffice, no layout models; the cases that need them are left out. full: the whole intake (assistant-x intake run)
in a temporary workspace: the texts, the drafts and the state it writes."""

import difflib, json, re, tempfile
from pathlib import Path

from tests.corpus import documents

MODES = ("fast", "full")
KEYS = ("phrase_recall", "heading_recall", "heading_precision", "ocr_accuracy", "verdict_accuracy", "meta_accuracy")


def norm(s):
    s = re.sub(r"<[^>]+>|[#*_`|\\]", " ", s or "").replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", s).strip().lower()


def found(phrase, text):
    return norm(phrase) in norm(text)


def heading_match(expected, got):
    a, b = norm(expected), norm(got)
    return bool(a) and bool(b) and (a in b or b in a)


def char_accuracy(text, source):
    return difflib.SequenceMatcher(None, norm(text), norm(source), autojunk=False).ratio()


def workspace(root):
    """A workspace of the corpus: the old edition in the library index as N-00001, the rest in inbox."""
    from assistant_x.core import config

    root = Path(root)
    cases = documents.make(root / "corpus")
    (root / "inbox").mkdir(exist_ok=True)
    for d in ("_duplicates", "_to_delete", "_rejected"):
        (root / "inbox" / d).mkdir(exist_ok=True)
    (root / "index" / "texts").mkdir(parents=True, exist_ok=True)
    for c in cases:
        src = root / "corpus" / ("library" if c["library"] else "inbox") / c["file"]
        if c["library"]:
            (root / "index" / "texts" / "N-00001.md").write_text(layer_md(src), encoding="utf-8", newline="\n")
        else:
            (root / "inbox" / c["file"]).write_bytes(src.read_bytes())
    path = root / "assistant_x.toml"
    path.write_text(
        config.dumps(
            {
                "profile": "oil-gas-ru",
                "paths": {"work": "work", "reports": "reports"},
                "intake": {
                    "soffice": "",
                    "tesseract": "",
                    "tessdata": "",
                    "sevenzip": "",
                    "workers": 1,
                    "priority": "normal",
                    "affinity": "all",
                    "regulate": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path, cases


def layer_pages(pdf):
    """[(page, text)] of the text layer as work.prep reads it and assemble_md writes it (the characters of the OCR font
    fixed, no invisible characters, NFC)."""
    import unicodedata
    import pymupdf
    from assistant_x.core.common import INVISIBLE_RX
    from assistant_x.intake.tools.ocr_page import FONT_FIX

    with pymupdf.open(pdf) as doc:
        return [
            (
                i + 1,
                unicodedata.normalize(
                    "NFC",
                    INVISIBLE_RX.sub(
                        "", p.get_text(flags=pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_DEHYPHENATE).translate(FONT_FIX)
                    ),
                ),
            )
            for i, p in enumerate(doc)
        ]


def layer_md(pdf):
    return "".join(f"=== page {n} ===\n\n{t.strip()}\n\n" for n, t in layer_pages(pdf))


def run_fast(root):
    """{case: {"pages": {n: text}, "headings": [...], "doc_type", "designation", "verdict", "drawing"}} by the fast way."""
    from assistant_x.core import textmap
    from assistant_x.intake import config as intake_cfg, metadraft
    from assistant_x.intake.process import Batch
    from assistant_x.intake.state import State
    from assistant_x.intake.tools import dupcheck, ocr_score, outline

    path, cases = workspace(root)
    cfg = intake_cfg.load(path)
    work = cfg.work / "corpus"
    (work / "txt").mkdir(parents=True, exist_ok=True)
    state = State(work / "state.sqlite")
    batch = Batch(cfg, work, state, 0)
    batch.lib["N-00001"] = dupcheck.library_fingerprint(str(cfg.index / "texts" / "N-00001.md"), str(work / "fp"))
    out = {}
    for c in cases:
        if c["library"] or c["needs"] == "soffice":
            if c["needs"] == "soffice":  # the heading styles of the DOCX at least
                out[c["name"]] = {"pages": {}, "headings": [g[1] for g in outline.docx_headings(root / "inbox" / c["file"])]}
            continue
        pdf = root / "inbox" / c["file"]
        pages = layer_pages(pdf)
        md = layer_md(pdf)
        given = outline.of_file(pdf)
        rows, _ = textmap.build([(n, t) for n, t in pages], given)
        d = metadraft.draft(md, c["file"], given=given)
        tid = state.add(c["file"], pdf.stat().st_size)
        (work / "txt" / f"{tid}.txt").write_text(md, encoding="utf-8")
        state.update(tid, pages=len(pages))
        fp = dupcheck.fingerprint("\n".join(t for _, t in pages[:30]))
        upd = batch.dup_verdict(tid, state.get(tid), fp)
        batch.mine[tid] = fp
        verdict = (
            ("dup", upd["dup_of"])
            if upd.get("status") == "dup"
            else ("suspect", upd["suspect"])
            if upd.get("suspect")
            else None
        )
        out[c["name"]] = {
            "pages": dict(pages),
            "headings": [r[1] for r in rows],
            "doc_type": d.get("doc_type"),
            "designation": d.get("code_hint"),
            "verdict": verdict,
            "drawing": ocr_score.pdf_is_drawing(str(pdf), len(" ".join(t for _, t in pages).split())),
        }
    return cases, out


def run_full(root):
    """The same by the whole intake: assistant-x intake run in the workspace of the corpus (LibreOffice and Tesseract
    when this PC has them); also the seconds of every file."""
    from assistant_x.core.common import split_pages
    from assistant_x.intake import config as intake_cfg, pipeline
    from assistant_x.intake.state import State

    path, cases = workspace(root)
    cfg = intake_cfg.load(path)
    if pipeline.main(["--config", str(path), "run", "--workers", "0"]) != 0:
        raise RuntimeError("the intake run of the corpus failed")
    work = sorted(cfg.work.glob("20??-??-??"))[-1]
    rows = {r["rel"]: r for r in State(work / "state.sqlite").all()}
    drafts = {}
    if (work / "meta_draft.jsonl").exists():
        drafts = {d["tid"]: d for d in map(json.loads, (work / "meta_draft.jsonl").read_text(encoding="utf-8").splitlines())}
    out = {}
    for c in cases:
        r = rows.get(c["file"])
        if c["library"] or r is None:
            continue
        md = work / "md" / f"{r['tid']}.md"
        if not md.exists():
            md = work / "mdtmp" / r["tid"] / f"{r['tid']}.dup.md"
        pages = dict(split_pages(md.read_text(encoding="utf-8"))) if md.exists() else {}
        d = drafts.get(r["tid"], {})
        title = lambda t: (
            " ".join((t.get("title") or {}).values()) if isinstance(t.get("title"), dict) else str(t.get("title"))
        )  # noqa: E731
        verdict = (
            ("dup", r.get("dup_of")) if r["status"] == "dup" else ("suspect", r["suspect"]) if r.get("suspect") else None
        )
        out[c["name"]] = {
            "pages": pages,
            "headings": [title(t) for t in d.get("toc", [])],
            "doc_type": d.get("doc_type"),
            "designation": d.get("code_hint"),
            "verdict": verdict,
            "drawing": bool(r.get("drawing")),
            "status": r["status"],
            "why": r.get("why"),
            "seconds": round((r.get("prep_seconds") or 0) + (r.get("convert_seconds") or 0), 1),
        }
    return cases, out


def score(cases, got, mode):
    """{"cases": {name: measures}, "totals": {KEYS}, "mode"}: the metrics of a run against the expectations."""
    per, tot = {}, {k: [0, 0] for k in ("phrase", "head_exp", "head_got", "verdict", "meta")}
    acc = []
    for c in cases:
        g = got.get(c["name"])
        if c["library"] or g is None:
            continue
        m = {}
        if mode == "full" or not c["needs"]:
            hits = [found(p, g["pages"].get(n, "")) for n, ps in c["phrases"].items() for p in ps]
            m["phrases"] = f"{sum(hits)}/{len(hits)}"
            tot["phrase"][0] += sum(hits)
            tot["phrase"][1] += len(hits)
        if c["headings"]:
            exp = [any(heading_match(e, h) for h in g["headings"]) for e in c["headings"]]
            ok = [any(heading_match(e, h) for e in c["headings"]) for h in g["headings"]]
            m["headings"] = f"{sum(exp)}/{len(exp)} found, {sum(ok)}/{len(ok)} right"
            tot["head_exp"][0] += sum(exp)
            tot["head_exp"][1] += len(exp)
            tot["head_got"][0] += sum(ok)
            tot["head_got"][1] += len(ok)
        if c["ocr_text"] and mode == "full":
            a = [char_accuracy(g["pages"].get(n, ""), t) for n, t in c["ocr_text"].items()]
            m["ocr_accuracy"] = round(sum(a) / len(a), 3)
            acc += a
        if mode == "full" or c["needs"] != "soffice":
            ok = g.get("verdict") == (tuple(c["verdict"]) if c["verdict"] else None)
            m["verdict"] = "ok" if ok else f"{g.get('verdict')} (expected {c['verdict']})"
            tot["verdict"][0] += ok
            tot["verdict"][1] += 1
            # a duplicate gets no draft; the state marks a drawing only when OCR read it (the fast way: by its sheet)
            dup = mode == "full" and c["verdict"] and c["verdict"][0] == "dup"
            checks = [(k, c[k], g.get(k)) for k in ("doc_type", "designation") if c[k] and not dup] + (
                [("drawing", True, g.get("drawing"))] if c["drawing"] and mode == "fast" else []
            )
            bad = [f"{k} {v!r} (expected {e!r})" for k, e, v in checks if v != e]
            m["meta"] = "ok" if not bad else "; ".join(bad)
            tot["meta"][0] += len(checks) - len(bad)
            tot["meta"][1] += len(checks)
        if "seconds" in g:
            m["seconds"] = g["seconds"]
        per[c["name"]] = m

    def share(k):
        return round(tot[k][0] / tot[k][1], 3) if tot[k][1] else None

    totals = {
        "phrase_recall": share("phrase"),
        "heading_recall": share("head_exp"),
        "heading_precision": share("head_got"),
        "ocr_accuracy": round(sum(acc) / len(acc), 3) if acc else None,
        "verdict_accuracy": share("verdict"),
        "meta_accuracy": share("meta"),
    }
    secs = [m["seconds"] for m in per.values() if "seconds" in m]
    if secs:
        totals["seconds"] = round(sum(secs), 1)
        totals["ocr_seconds"] = round(
            sum(per[c["name"]].get("seconds", 0) for c in cases if c["needs"] == "ocr" and c["name"] in per), 1
        )
    return {"mode": mode, "cases": per, "totals": totals}


def measure(mode="fast", root=None):
    """Run the corpus in a temporary folder (or root) and score it."""
    if root is None:
        with tempfile.TemporaryDirectory(prefix="ax_corpus_") as d:
            return measure(mode, d)
    cases, got = (run_fast if mode == "fast" else run_full)(Path(root))
    return score(cases, got, mode)


def below(report, baseline, tolerance=0.005):
    """The metrics of a report under their baseline (more than tolerance): [(key, value, baseline)]."""
    out = []
    for k, b in (baseline or {}).items():
        v = report["totals"].get(k)
        if k in KEYS and b is not None and (v is None or v < b - tolerance):
            out.append((k, v, b))
    return out
