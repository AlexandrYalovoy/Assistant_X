# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-run pages that converted to (almost) nothing, and the scanned pages of a job ("ocr_pages": a stamp or a header
in the text layer of a scan) the conversion did not recognise, forcing OCR; results override the cache.
Usage: python -m assistant_x.intake.tools.reocr_empty <jobs.json> <cache_dir> [workers]
A chunk that fails makes the exit code 1; a cache file is written whole or not at all (temporary file, then rename).
workers 0: the chunks one after another in this process (a persistent worker of intake.py calls main()).
OCR as in convert_md (ocr_page.exec_ocr); the measures go to <cache_dir>/<code>/ocr/z_force_<chunk>.json."""

import sys, os, json, glob
from concurrent.futures import ProcessPoolExecutor, as_completed

from assistant_x.intake.tools import onnx_threads
from assistant_x.intake.tools.convert_md import OCR_CHUNK as CHUNK, close_all, markdown, ocr_out, write_json


def run(path, shift, pages, out):
    onnx_threads.limit()
    res, stats = markdown(path, shift, pages, True)
    write_json(stats, ocr_out(out))
    write_json(res, out)
    return len(pages)


def main(argv):
    jobs, cache = json.load(open(argv[0], encoding="utf-8")), argv[1]
    workers = int(argv[2]) if len(argv) > 2 else 4
    tasks = []
    for code, job in jobs.items():
        new = {}
        for f in glob.glob(f"{cache}/{code}/0*.json"):
            try:
                with open(f, encoding="utf-8") as fh:
                    new.update({int(k): v for k, v in json.load(fh).items()})
            except (ValueError, AttributeError) as e:  # removed: the next run converts these pages again
                os.remove(f)
                sys.exit(f"ERROR {f}: a broken cache was deleted, the piece has to be converted again: {e!r}")
        seen = set()  # the pages convert_md recognised by OCR already
        for f in glob.glob(f"{cache}/{code}/ocr/*.json"):
            try:
                with open(f, encoding="utf-8") as fh:
                    seen.update(int(k) for k in json.load(fh))
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        scans = set(job.get("ocr_pages") or []) - seen
        empty = sorted(n for n, v in new.items() if sum(c.isalpha() for c in v) < 20 or n in scans)
        for path, first in job["parts"]:
            import pymupdf

            last = first + pymupdf.open(path).page_count - 1
            mine = [n - first for n in empty if first <= n <= last]
            for s in range(0, len(mine), CHUNK):
                part = mine[s : s + CHUNK]
                out = f"{cache}/{code}/z_force_{part[0] + first:05d}.json"
                if not os.path.exists(out):
                    tasks.append((path, first - 1, part, out))
    print(f"pages to re-OCR: {sum(len(t[2]) for t in tasks)}", flush=True)
    done, failed = 0, 0

    def finished(t, get):
        nonlocal done, failed
        try:
            done += get()
            print(f"{done} pages", flush=True)
        except MemoryError:
            raise  # the worker is past its memory cap: intake.py restarts it
        except Exception as e:
            failed += 1
            print(f"ERROR {t[3]}: {e!r}", file=sys.stderr, flush=True)

    if workers > 0 and tasks:
        with ProcessPoolExecutor(workers) as ex:
            futs = {ex.submit(run, *t): t for t in tasks}
            for f in as_completed(futs):
                finished(futs[f], f.result)
    else:
        try:
            for t in tasks:
                finished(t, lambda t=t: run(*t))
        finally:
            close_all()
    if failed:
        sys.exit(f"pieces not recognized: {failed} of {len(tasks)}")


if __name__ == "__main__":
    main(sys.argv[1:])
