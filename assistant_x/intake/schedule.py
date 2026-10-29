# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The order and the concurrency of the tasks of a batch (process.Batch): the policy alone, without the pool, so it is
tested by itself.

- The cost of a file is its estimated seconds after prep: its text pages and its scanned pages at the speeds measured
  on the first real batch (audit 6: a text page 0.2–1 s, a scanned one 2.5–9 s), a text page with a picture a second
  more (its one OCR reading). Cheap tasks go first: a small file never waits behind a big scan (M-011).
- A heavy task (a long estimate, a thick document, a file that needed a bigger memory cap) gets its memory cap by
  pages (Batch.memory_for). Heavy tasks run side by side while their caps fit into the free memory of the PC (psutil,
  minus the reserve of balance.py, 70 % of it), re-evaluated at every admission; one worker stays for light tasks while
  there are any (M-014).
- The OCR of a long scan, or of a long text with pictures on its pages (a scan with a visible layer), is cut into page ranges (shards) that the persistent pool runs as tasks of their own, on
  every worker; the Markdown is assembled when all of them are back, from the cache of convert_md (M-020).
  [intake] ocr_shards = "off" turns the cutting off (the conversion of a document in one task, as in 0.1)."""

import heapq, itertools, math

# seconds per page measured on the first real batch (audit 6): a text page, a scanned page read by OCR
TEXT_SECONDS, SCAN_SECONDS = 0.5, 3.3
PICTURE_SECONDS = 2.0  # more for a text page with a picture: its OCR reading (pipeline test round 1: 2.1-3.6 s)
SHEET_SECONDS = 25.0  # a drawing sheet of A2 and up without a text layer (trial batches b014-b029: 25-30 s a sheet)
SHEET_WEIGHT = 8  # a sheet counts as this many scanned pages when a document is cut into page ranges
HEAVY_SECONDS = 900  # an estimate from which a task is heavy (15 min of one worker)
HEAVY_SHARE = 0.7  # the share of the free memory (past the reserve) the caps of heavy tasks may take together
SHARD_MIN = 30  # pages read by OCR (scanned, or text pages with a picture) from which a document is cut into ranges
SHARD_PAGES = 20  # pages read by OCR of a range at least (a range is a task: fewer would cost more than they save)
SHARD_WORKERS = 3  # page ranges of one document a worker at most
# a long document of text pages is cut too (trial batch b103: a workbook laid out on 1 029 pages of tables, 1.7 s a
# page in the layout analysis, held one worker half an hour while fifteen waited): ranges of TEXT_SHARD_PAGES at least
TEXT_SHARD_MIN, TEXT_SHARD_PAGES = 300, 100
SHARD_MODES = ("auto", "off")


def cost(pages, scans=0, image_pages=0, sheets=0):
    """Estimated seconds of the conversion of a document of `pages` pages, `scans` of them scanned, `image_pages` of
    the others with a picture and `sheets` drawing sheets without a text layer."""
    scans = min(scans or 0, pages or 0)
    sheets = min(sheets or 0, (pages or 0) - scans)
    pictures = min(image_pages or 0, (pages or 0) - scans - sheets)
    text = (pages or 0) - scans - sheets
    return round(text * TEXT_SECONDS + scans * SCAN_SECONDS + pictures * PICTURE_SECONDS + sheets * SHEET_SECONDS, 1)


def heavy(cost_s, pages, thick):
    """Is a task heavy: a long estimate, or a document past THICK pages."""
    return cost_s >= HEAVY_SECONDS or (pages or 0) > thick


def shard_count(scans, workers, pages_read=None):
    """Into how many page ranges the OCR of a document of `scans` scanned pages (a drawing sheet counted SHEET_WEIGHT
    times) is cut (1: not cut): up to SHARD_WORKERS ranges a worker, so the last ranges of a long scan, started behind
    the cheaper files, are short (round 3 of the pipeline test: twelve ranges of 46 pages of a 558-page book ran 200 s
    each at the end of the batch); never more ranges than the pages read (pages_read)."""
    if workers < 2 or scans < SHARD_MIN:
        return 1
    k = max(1, min(SHARD_WORKERS * workers, scans // SHARD_PAGES))
    return min(k, pages_read) if pages_read else k


def text_shard_count(pages, workers):
    """Into how many page ranges a long document whose pages OCR does not read is cut (1: not cut)."""
    if workers < 2 or (pages or 0) < TEXT_SHARD_MIN:
        return 1
    return max(1, min(SHARD_WORKERS * workers, pages // TEXT_SHARD_PAGES))


def shard_ranges(pages, scan_pages, k):
    """k ranges [(first, last)] of PDF pages 1..pages, one after another and together all of them, each with about the
    same number of the scanned pages scan_pages."""
    if k <= 1 or not scan_pages:
        return [(1, pages)]
    scans = sorted(p for p in set(scan_pages) if 1 <= p <= pages)
    per = len(scans) / k
    cuts = [scans[min(len(scans) - 1, math.ceil(per * i))] for i in range(1, k)]
    starts = [1] + sorted(set(c for c in cuts if c > 1))
    out = []
    for i, a in enumerate(starts):
        b = starts[i + 1] - 1 if i + 1 < len(starts) else pages
        out.append((a, b))
    return out


def tail(preps_left, ready, workers):
    """The tail of a batch: every file prepared and no more tasks ready than workers: the longest go first."""
    return not preps_left and 0 < ready <= workers


def heavy_budget_mb(avail_gb, reserve_gb):
    """The memory heavy tasks may take together: HEAVY_SHARE of the free memory past the reserve."""
    return max(0.0, (avail_gb - reserve_gb) * 1024 * HEAVY_SHARE)


def may_admit_heavy(cap_mb, heavy_caps_mb, budget_mb, light_left, heavy_running, workers):
    """May a heavy task of cap_mb start now? Always when no heavy one runs; else while the caps fit into the budget and,
    with light work still to do, one worker stays for it."""
    if not heavy_running:
        return True
    if light_left and heavy_running >= max(1, workers - 1):
        return False
    return sum(heavy_caps_mb) + cap_mb <= budget_mb


class Ready:
    """The tasks ready to start, cheapest first (then in the order they came)."""

    def __init__(self):
        self.heap, self.seq = [], itertools.count()

    def push(self, cost_s, item, is_heavy=False):
        heapq.heappush(self.heap, (cost_s, next(self.seq), is_heavy, item))

    def __len__(self):
        return len(self.heap)

    def light(self):
        return any(not h for _, _, h, _ in self.heap)

    def take(self, may_heavy, longest=False):
        """The cheapest task, or the cheapest light one when a heavy one may not start; None when there is none.
        longest: the costliest first (the tail of a batch, tail(): a long range started last would hold the batch
        alone at its end, P4)."""
        tasks = sorted(self.heap, key=lambda x: (-x[0], x[1])) if longest else sorted(self.heap)
        for i, (c, s, h, item) in enumerate(tasks):
            if not h or may_heavy(item):
                self.heap.remove((c, s, h, item))
                heapq.heapify(self.heap)
                return item
        return None
