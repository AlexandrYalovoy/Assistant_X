# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the stages of a file pass to each other: the job a worker gets (process.Batch.job) and the results of prep and
convert (work.py) that the main process writes into the state of the file (state.py: the keys go into its data as
they are). Plain dicts across processes, described here once; every key may be missing, so a reader uses .get()."""

from typing import TypedDict


class Job(TypedDict, total=False):
    """A task of a worker: the settings of the batch (Batch.base) and the file."""

    work: str  # the work folder of the batch
    tid: str  # T0001
    rel: str  # its path in inbox, "/" between folders
    src: str  # the original in inbox
    ext: str  # its extension, lower case
    soffice: str | None  # LibreOffice, None: not installed
    ddjvu: str | None  # DjVuLibre, None: not installed
    ocr: bool  # Tesseract with the languages of the packs is there
    timeouts: dict  # [intake] timeouts (core/config.INTAKE)
    memory_mb: int  # the memory cap of a tool process
    env: dict  # the environment of the tool processes
    ocr_threads: int
    inproc: bool  # the tools run as functions in a persistent worker
    imgocr: bool  # recognise the page images instead of the text layer (a broken font encoding)
    pdf: str  # convert: the PDF prep made
    ocr_pages: int  # convert: how many pages are scans
    scan_pages: list  # convert: which ones (PDF pages from 1): OCR even with a stamp in their text layer
    phrases: int  # convert: the phrases of the fingerprint of the text layer (few: a scan)


class Prep(TypedDict, total=False):
    """The result of work.prep."""

    status: str  # "prepped", "error", "skipped"
    why: str  # the reason of an error or a skip; of imgocr too
    pages: int
    hidden: int  # characters of hidden text (tools/hidden.py)
    hidden_pages: list
    hidden_check: str  # the hidden text check did not finish
    imgocr: bool  # prep saw a broken font encoding: the page images go to OCR
    pdf: str  # the PDF convert reads
    fp: list  # the fingerprint of the text layer (dupcheck), popped by Batch.handle
    phrases: int
    ocr_pages: int
    scan_pages: list
    prep_seconds: float


class Convert(TypedDict, total=False):
    """The result of work.convert."""

    status: str  # "converted", "error"
    why: str
    letters: dict  # {language pack: the share of its letters in the text} (core/common.letter_shares)
    chars: int
    fffd: int  # lost symbols U+FFFD: more than 100 sends the file back to prep with imgocr
    fallback: int  # pages that fell back to the text layer
    tables: int
    invisible_chars: int
    no_ocr_pages: int  # scan pages left without OCR (no Tesseract)
    convert_seconds: float
    ocr_score: float  # the recognition score (work.ocr_measures)
    ocr_nonword: float
    ocr_low_pages: int
    ocr_conf: float
    ocr_retried: int
    ocr_rotated: int
    ocr_garbled_pages: int
    ocr_doubled_pages: int  # pages whose every phrase appears twice (ocr_score.repeated)
    ocr_layer_kept: int  # pages whose legible text layer made their recognition needless (ocr_page.beside_layer)
    drawing: bool
    fp: list  # the fingerprint of the recognised text of a scan
    phrases: int
