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


def hold(mb, seconds):
    block = bytearray(mb * 1024 * 1024)
    for i in range(0, len(block), 4096):  # touched: resident memory
        block[i] = 1
    time.sleep(seconds)
    return len(block)


def boom():
    raise ValueError("broke inside the task")


def noisy(job):
    """Writes as a tool does: a print, the descriptor itself, a child process that inherits the output."""
    import sys

    from assistant_x.core import proc

    print("from python", flush=True)
    os.write(2, b"from the descriptor\n")
    proc.run([sys.executable, "-c", "print('from a child')"], timeout=60)
    return {"status": "ok"}
