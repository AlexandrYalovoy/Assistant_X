# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tasks for the persistent workers of intake_pool in test_intake_pool.py (a worker imports them by name)."""

import os, time


def pid():
    return os.getpid()


def crash(code):
    os._exit(code)


def nap(seconds):
    time.sleep(seconds)
    return seconds


def hog(mb):
    block = bytearray(mb * 1024 * 1024)
    return len(block)


def boom():
    raise ValueError("broke inside the task")
