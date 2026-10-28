# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Tesseract languages are downloaded from a commit, never from a moving branch: a change upstream would break the
install (the pinned sha256 would refuse it), and a language of a user's pack has no sha256 to guard it at all."""

import re

from assistant_x.setup import downloads, setup_intake

COMMIT = re.compile(r"/raw/[0-9a-f]{40}/")


def test_every_tesseract_download_names_a_commit():
    for url, sha in downloads.TESSDATA.values():
        assert COMMIT.search(url) and len(sha) == 64, url
    assert COMMIT.search(setup_intake.TESSDATA_URL.format("deu")) and "/main/" not in setup_intake.TESSDATA_URL
