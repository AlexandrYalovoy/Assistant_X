# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""MuPDF writes its messages to the stdout of the moment: pymupdf keeps the stream of its import, and a stream closed
since then (a test that captured the output: test_workspace before test_metadraft_rules) failed every conversion of
the process with "I/O operation on closed file"."""

import io

import pymupdf

from assistant_x.intake.tools import convert_md


def test_a_closed_stream_of_the_import_breaks_no_conversion(tmp_path):
    pdf = tmp_path / "a.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    gone = io.StringIO()
    pymupdf.set_messages(stream=gone)  # as if pymupdf had been imported under a captured stdout
    pymupdf._ax_messages = None
    gone.close()
    try:
        assert convert_md.open_pdf(str(pdf)).page_count == 1
        pymupdf.message("a message of MuPDF")  # goes to the stdout of now
    finally:
        convert_md.close_all()
