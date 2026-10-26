# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every test runs on temporary folders: the workspace of the tests (AX_WORKSPACE), the machine lock, the speeds and the
model fingerprints of the PC are made here,
before any module of assistant_x is imported, so nothing is written into the code folder, the user's Documents or
%LOCALAPPDATA%."""

import os, shutil, tempfile

_ROOT = tempfile.mkdtemp(prefix="ax_tests_")
os.environ["AX_WORKSPACE"] = os.path.join(_ROOT, "workspace")
os.environ["AX_MACHINE_DIR"] = os.path.join(_ROOT, "machine")  # the folder of the PC: models, program, locks
os.environ["AX_HEAVY_LOCK_FILE"] = os.path.join(_ROOT, "heavy.lock")
os.environ["AX_SPEED_FILE"] = os.path.join(_ROOT, "speed.json")
os.environ["AX_MCP_LOCK_FILE"] = os.path.join(_ROOT, "mcp_server.lock")
os.environ["AX_MODEL_FINGERPRINTS"] = os.path.join(_ROOT, "model_fingerprints.json")
os.environ["AX_PROGRAMS"] = os.environ.get("AX_PROGRAMS") or os.path.join(_ROOT, "programs")
os.environ["AX_NO_OPEN"] = "1"
# the workspace of the tests reads its documents with the profile of the fixtures (oil and gas, Russian documents)
os.makedirs(os.environ["AX_WORKSPACE"], exist_ok=True)
with open(os.path.join(os.environ["AX_WORKSPACE"], "assistant_x.toml"), "w", encoding="utf-8") as _f:
    _f.write('profile = "oil-gas-ru"\n')
for _name in ("AX_CONFIG", "AX_SEARCH_CONFIG", "AX_HEAVY_LOCK"):
    os.environ.pop(_name, None)


def pytest_unconfigure(config):
    shutil.rmtree(_ROOT, ignore_errors=True)
