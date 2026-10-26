# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of the intake on the PC (intake). Everything runs in temporary folders (intake_fixtures.make_project).
Fast tests run before every commit; the whole pipeline is marked slow: python -m pytest -m slow tests/intake"""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: whole intake pipeline (LibreOffice, OCR), not run by pre-commit")


@pytest.fixture(autouse=True)
def heavy_lock(tmp_path, monkeypatch):
    """The machine lock of the tests is a temporary file: a real intake or eval on the PC does not stop them."""
    monkeypatch.setenv("AX_HEAVY_LOCK_FILE", str(tmp_path / "heavy.lock"))
    monkeypatch.delenv("AX_HEAVY_LOCK", raising=False)
    return tmp_path / "heavy.lock"


@pytest.fixture
def project(tmp_path):
    """A temporary project without LibreOffice; returns (root, loaded config)."""
    from assistant_x.intake import config as intake_cfg
    from tests.intake.intake_fixtures import make_project

    path = make_project(tmp_path / "Проект")  # a Cyrillic folder, as in a Russian user profile
    return tmp_path / "Проект", intake_cfg.load(path)
