# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the search and the intake share lives in core: the boundaries of the modules, the paths of the workspace
resolved when they are used (not when a module is imported), one place of the intake defaults, one table of file
kinds."""

import ast
from pathlib import Path

import pytest

from assistant_x.core import config, formats, workspace

PACKAGE = Path(__file__).resolve().parents[1] / "assistant_x"
# the intake may write the catalog of the library (apply); everything else it needs of the search is in core
ALLOWED = {("intake", "assistant_x.search.catalog")}


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            yield from (a.name for a in node.names)


@pytest.mark.parametrize("side, other", [("intake", "search"), ("search", "intake")])
def test_intake_and_search_meet_in_core(side, other):
    bad = []
    for p in sorted((PACKAGE / side).rglob("*.py")):
        for m in set(imports(p)):
            if m.startswith(f"assistant_x.{other}") and m != f"assistant_x.{other}" and (side, m) not in ALLOWED:
                bad.append(f"{p.relative_to(PACKAGE)}: {m}")
    assert not bad


def test_workspace_paths_resolved_at_the_call(tmp_path, monkeypatch):
    from assistant_x.intake.tools import dupcheck, ocr_score

    for name in ("a", "b"):
        monkeypatch.setenv("AX_WORKSPACE", str(tmp_path / name))
        monkeypatch.delenv("AX_TEXTS", raising=False)
        monkeypatch.delenv("AX_FP_CACHE", raising=False)
        w = workspace.Workspace(tmp_path / name)
        assert dupcheck.texts_dir() == str(w.texts) and dupcheck.cache_dir() == str(w.fingerprints)
        assert ocr_score.vocab_file() == str(w.ocr_vocab) and ocr_score.texts_dir() == str(w.texts)
    monkeypatch.setenv("AX_TEXTS", str(tmp_path / "texts"))
    monkeypatch.setenv("AX_FP_CACHE", str(tmp_path / "fp"))
    assert dupcheck.texts_dir() == str(tmp_path / "texts") and dupcheck.cache_dir() == str(tmp_path / "fp")


def test_manifest_of_a_given_root(tmp_path):
    from assistant_x.intake import manifest

    (tmp_path / "library" / "01_Standards").mkdir(parents=True)
    (tmp_path / "index").mkdir()
    (tmp_path / "library" / "01_Standards" / "N-00001_A.pdf").write_bytes(b"%PDF-1.4")
    manifest.main(["--root", str(tmp_path)])
    rows = manifest.load(manifest.manifest_path(tmp_path))
    assert (
        list(rows) == ["library\\01_Standards\\N-00001_A.pdf"]
        and rows["library\\01_Standards\\N-00001_A.pdf"]["code"] == "N-00001"
    )


def test_one_place_of_the_intake_defaults(tmp_path, monkeypatch):
    for k in ("STAGE_MODE", "PRIORITY", "AFFINITY", "PROFILE", "WORKERS", "OCR_THREADS", "WORKER_MEMORY_MB"):
        monkeypatch.delenv("AX_" + k, raising=False)  # an inline worker of another test leaves its environment
    from assistant_x.core import common
    from assistant_x.intake import balance, config as intake_cfg, work
    from assistant_x.intake.tools import unpack

    path = tmp_path / workspace.CONFIG
    path.write_text("[intake]\nworkers = 3\n[intake.timeouts]\nconvert = 60\n", encoding="utf-8")
    cfg = intake_cfg.load(path)
    d = config.INTAKE
    assert cfg.workers == 3 and cfg.timeouts == {**d["timeouts"], "convert": 60}
    assert cfg.unpack == d["unpack"] and cfg.disk == d["disk"] == common.DISK and cfg.heavy_mb == d["heavy_mb"]
    assert cfg.stage_mode == d["stage_mode"] and cfg.priority == d["priority"] == balance.DEFAULT_PRIORITY
    assert balance.OPTIONS["idle_minutes"] == d["idle_minutes"] and balance.OPTIONS["temp_max_c"] == d["temp_max_c"]
    assert unpack.TIMEOUT == d["timeouts"]["unpack"] and unpack.LIMITS == d["unpack"]
    t = d["timeouts"]
    assert work.task_timeout(work.prep, ({},)) == t["soffice"] + t["hidden"] + 600


def test_one_table_of_file_kinds():
    from assistant_x.intake import batch, metadraft, work
    from assistant_x.intake.tools import unpack

    assert work.OFFICE == set(formats.extensions("office")) and work.IMAGES == metadraft.IMAGES == set(
        formats.extensions("image")
    )
    assert batch.LETTERS == {"msg", "eml", "oft"} and batch.EXCEL == {"xls", "xlsx", "xlsm", "xlsb", "ods"}
    assert unpack.ARCHIVES == (".zip", ".7z", ".rar", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz", ".gz") + (
        ".7z.001",
        ".zip.001",
        ".rar.001",
        ".001",
    )  # the first volume of a split archive
    assert [
        formats.file_kind(n)
        for n in ("A.PDF", "b.tar.gz", "c.docx", "d.eml", "e.xlsb", "f.djvu", "h.epub", "i.md", "j.htm", "k.xyz", "g")
    ] == ["pdf", "archive", "office", "letter", "spreadsheet", "djvu", "ebook", "text", "text", "", ""]
    assert set(formats.EXTENSIONS.values()) <= set(formats.FILE_KINDS)
    with pytest.raises(ValueError):
        formats.extensions("video")


def test_text_map_shared_by_search_and_intake():
    from assistant_x.core import common, textmap
    from assistant_x.search import bookmap

    assert bookmap.build is textmap.build and bookmap.toc_entries is textmap.toc_entries
    assert common.heading_text is textmap.heading_text and common.SectionTracker is textmap.SectionTracker
    from assistant_x.core import journal
    from assistant_x.intake import journal as old

    assert old.sync is journal.sync and old.main is journal.main


def test_places_of_cards_on_every_system():
    """A card names its files with backslashes on every system; on disk they are joined with the separator of the OS,
    and the hidden text scan finds the code in both forms."""
    import os

    from assistant_x.intake.tools import hidden_scan

    assert formats.place_of(os.path.join("01_Standards", "N-00001_GOST.pdf")) == "01_Standards\\N-00001_GOST.pdf"
    want = os.sep.join(["root", "library", "01_Standards", "N-00001_GOST.pdf"])
    assert formats.place_path("root", "library\\01_Standards\\N-00001_GOST.pdf") == want
    assert formats.place_path("root", "library/01_Standards/N-00001_GOST.pdf") == want
    assert hidden_scan.code_of("library\\01_Standards/N-00001_GOST.pdf") == "N-00001"


def test_the_model_commands_keep_the_libraries_quiet(monkeypatch):
    """The quiet environment goes where the user set nothing; a value of the user stays (core/env.QUIET)."""
    import logging, os, warnings

    from assistant_x.core import env

    assert env.quiet({"TQDM_DISABLE": "0"})["TQDM_DISABLE"] == "0" and env.quiet({})["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
    monkeypatch.setattr(os, "environ", {"PYTHONWARNINGS": "default"})
    log = logging.getLogger("torch.distributed.elastic.multiprocessing.redirects")
    level = log.level
    try:
        with warnings.catch_warnings():
            env.quiet_here()
        assert os.environ["TQDM_DISABLE"] == "1" and os.environ["PYTHONWARNINGS"] == "default"
        assert log.level == logging.ERROR
    finally:
        log.setLevel(level)
