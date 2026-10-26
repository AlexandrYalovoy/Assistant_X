# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stability of the intake: one intake at a time (intake_lock), tool exit codes, cache files written whole,
free disk space before run, the pause between backups."""

import json, os, subprocess, sys, time, tomllib
from pathlib import Path

import pytest

from assistant_x.intake import pipeline as intake
from assistant_x.core import lock as intake_lock
from assistant_x.intake import work as intake_work
from tests.intake.intake_fixtures import GOST_PAGES, text_pdf

CODE = Path(__file__).resolve().parents[2]  # the folder of the code


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


# ---------- the lock ----------


def test_lock_second_start_refused_and_released(tmp_path):
    with intake_lock.hold(tmp_path, "run") as path:
        owner = json.loads(Path(path).read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid() and owner["command"] == "run" and owner["time"]
        with pytest.raises(intake_lock.FolderBusy, match="An intake is running already: run"):
            intake_lock.acquire(tmp_path, "apply")
    assert not (tmp_path / intake_lock.NAME).exists()


def test_lock_released_after_error(tmp_path):
    with pytest.raises(RuntimeError):
        with intake_lock.hold(tmp_path, "apply"):
            raise RuntimeError("failure")
    assert not (tmp_path / intake_lock.NAME).exists()


def test_dead_lock_removed(tmp_path):
    pid = dead_pid()
    assert not intake_lock.alive(pid)
    (tmp_path / intake_lock.NAME).write_text(
        json.dumps({"pid": pid, "time": "2026-01-01T00:00:00", "ts": time.time() - 60}), encoding="utf-8"
    )
    path = intake_lock.acquire(tmp_path, "run")
    assert json.loads(Path(path).read_text(encoding="utf-8"))["pid"] == os.getpid()
    intake_lock.release(path)


def test_intake_commands_refused_while_locked(project):
    root, cfg = project
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        cfg.work.mkdir(parents=True, exist_ok=True)
        (cfg.work / intake_lock.NAME).write_text(
            json.dumps({"pid": owner.pid, "time": "now", "ts": time.time(), "command": "run"}), encoding="utf-8"
        )
        for cmd in (["run"], ["requeue", "T0001"], ["apply"]):
            with pytest.raises(intake_lock.FolderBusy, match=f"process {owner.pid}"):
                intake.main(["--config", str(cfg.path)] + cmd)
        assert (cfg.inbox / "Письма" / "note.eml").exists()  # run did not start
    finally:
        owner.kill()
        owner.wait()
    (cfg.work / "2026-10-23").mkdir()
    from assistant_x.intake.state import State

    State(cfg.work / "2026-10-23" / "state.sqlite")
    assert intake.main(["--config", str(cfg.path), "requeue"]) == 0  # the dead owner's lock is taken over
    assert not (cfg.work / intake_lock.NAME).exists()


# ---------- exit codes of the tools ----------


def fake_tools(d, **codes):
    """Tools that write a line to stderr and stop with the code given (0: the real tool is not needed)."""
    d.mkdir()
    for name, rc in codes.items():
        (d / f"{name}.py").write_text(
            f"import sys\nprint('step running')\nprint('Traceback: everything broke in {name}', file=sys.stderr)\n"
            f"sys.exit({rc})\n",
            encoding="utf-8",
        )
    return lambda name: [sys.executable, str(d / name)]


def job(tmp_path, **kw):
    w = tmp_path / "work"
    for d in ("log", "txt"):
        (w / d).mkdir(parents=True, exist_ok=True)
    pdf = tmp_path / "a.pdf"
    text_pdf(pdf, GOST_PAGES)
    return {
        "work": str(w),
        "tid": "T0001",
        "rel": "a.pdf",
        "src": str(pdf),
        "ext": "pdf",
        "pdf": str(pdf),
        "ocr": False,
        "soffice": None,
        "timeouts": {"hidden": 60, "convert": 60, "soffice": 60},
        "memory_mb": 0,
        "env": dict(os.environ),
        "ocr_threads": 1,
        **kw,
    }


def test_convert_tool_failure_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_work, "tool_cmd", fake_tools(tmp_path / "tools", convert_md=2))
    res = intake_work.convert(job(tmp_path))
    assert res["status"] == "error"
    assert "conversion to Markdown: code 2" in res["why"] and "everything broke in convert_md" in res["why"]
    assert not (tmp_path / "work" / "md" / "T0001.md").exists()  # no fallback text instead


def test_reocr_failure_is_error(tmp_path, monkeypatch):
    tools = fake_tools(tmp_path / "tools", convert_md=0, reocr_empty=1)
    monkeypatch.setattr(intake_work, "tool_cmd", tools)
    res = intake_work.convert(job(tmp_path, ocr=True))
    assert res["status"] == "error" and res["why"].startswith("OCR of empty pages: code 1")


def test_hidden_check_crash_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_work, "tool_cmd", fake_tools(tmp_path / "tools", hidden=3))
    res = intake_work.prep(job(tmp_path))
    assert res["status"] == "error" and res["why"].startswith("the hidden text check: code 3")


def test_convert_md_exit_code_on_failed_chunk(tmp_path):
    bad = tmp_path / "bad.pdf"
    text_pdf(bad, GOST_PAGES)
    jobs = tmp_path / "jobs.json"
    jobs.write_text(
        json.dumps({"T0001": {"parts": [[str(bad), 1]], "force_ocr": False, "use_ocr": False}}), encoding="utf-8"
    )
    # a chunk fails when its PDF disappears after the pages were counted: here the cache folder is a file
    cache = tmp_path / "cache"
    (cache / "T0001").mkdir(parents=True)
    (cache / "T0001" / "00001.json.tmp").mkdir()
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-I", "-m", "assistant_x.intake.tools.convert_md", str(jobs), str(cache), "1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 1 and "pieces not converted: 1" in r.stderr


# ---------- cache files ----------


def test_reocr_cache_written_whole(tmp_path, monkeypatch):
    from assistant_x.intake.tools import reocr_empty

    pdf = tmp_path / "a.pdf"
    text_pdf(pdf, GOST_PAGES)
    fake = type(sys)("pymupdf4llm")
    fake.to_markdown = lambda doc, pages, **kw: [{"metadata": {"page_number": p + 1}, "text": f"page {p}"} for p in pages]
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake)
    out = str(tmp_path / "z_force_00001.json")
    assert reocr_empty.run(str(pdf), 0, [0, 1], out) == 2
    assert json.loads(Path(out).read_text(encoding="utf-8")) == {"1": "page 0", "2": "page 1"}
    assert not os.path.exists(out + ".tmp")

    def broken(obj, f, **kw):
        f.write('{"1": "brok')
        raise OSError("disk disconnected")

    monkeypatch.setattr(reocr_empty.json, "dump", broken)
    out2 = str(tmp_path / "z_force_00011.json")
    with pytest.raises(OSError):
        reocr_empty.run(str(pdf), 0, [0], out2)
    assert not os.path.exists(out2)  # no half-written cache that assemble_md would trust


def test_assemble_drops_broken_cache(tmp_path):
    (tmp_path / "txt").mkdir()
    (tmp_path / "txt" / "T0001.txt").write_text(
        "\n=== page 1 ===\nТекст слоя страницы один\n\n=== page 2 ===\nТекст слоя два\n", encoding="utf-8"
    )
    c = tmp_path / "cache" / "T0001"
    c.mkdir(parents=True)
    (c / "00001.json").write_text(
        json.dumps({"1": "# Страница один\n\nТекст слоя страницы один разобранный"}), encoding="utf-8"
    )
    (c / "z_force_00002.json").write_text('{"2": "brok', encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-I",
            "-m",
            "assistant_x.intake.tools.assemble_md",
            str(tmp_path / "txt"),
            str(tmp_path / "cache"),
            str(tmp_path / "out"),
            "T0001",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    assert "WARNING" in r.stderr and "a broken cache was deleted" in r.stderr
    assert not (c / "z_force_00002.json").exists() and (c / "00001.json").exists()
    md = (tmp_path / "out" / "T0001.md").read_text(encoding="utf-8")
    assert "# Страница один" in md and "Текст слоя два" in md


# ---------- free space before run ----------


def test_run_refused_on_low_disk(project):
    root, cfg = project
    from assistant_x.intake import config as intake_cfg

    intake_cfg.save({"disk": {"factor": 3, "min_free_gb": 10**9}}, cfg.path)
    with pytest.raises(SystemExit, match="Not enough disk space on"):
        intake.main(["--config", str(cfg.path), "run", "--workers", "0"])
    assert (cfg.inbox / "Письма" / "note.eml").exists() and (cfg.inbox / "Архив.zip").exists()  # nothing was moved
    assert not (cfg.work / intake_lock.NAME).exists()


def test_disk_settings_in_the_settings(project):
    import tomllib
    from assistant_x.core import config

    root, cfg = project
    assert cfg.disk == {"factor": 3, "min_free_gb": 10} == config.INTAKE["disk"]
    (root / "assistant_x.toml").write_text(
        (root / "assistant_x.toml").read_text(encoding="utf-8") + "\n[intake.disk]\nmin_free_gb = 20\n", encoding="utf-8"
    )
    from assistant_x.intake import config as intake_cfg

    assert intake_cfg.load(root / "assistant_x.toml").disk == {"factor": 3, "min_free_gb": 20}
    template = tomllib.loads((CODE / "assistant_x" / "templates" / "assistant_x.toml").read_text(encoding="utf-8"))
    assert set(template) == {"profile", "documents", "paths", "search", "intake"} and template["profile"] == "general"


# ---------- debug and the backup ----------


def test_debug_folder_ignored():
    root = CODE
    r = subprocess.run(["git", "check-ignore", "-q", "debug/x.txt"], cwd=root)
    assert r.returncode == 0
    tracked = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "debug"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert tracked == ""


# ---------- programs: programs/ first, settings of another PC do not stop the search, paths of this PC aside ----------


def fake_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    return path


def test_programs_bundled_first_and_missing_setting_searched(tmp_path, monkeypatch):
    from assistant_x.intake import config as intake_cfg

    progs = tmp_path / "programs"
    monkeypatch.setenv("AX_PROGRAMS", str(progs))
    win = os.name == "nt"  # the names of the programs of this system: a bundled copy is looked for by them
    other = fake_exe(tmp_path / "other" / ("tesseract.exe" if win else "tesseract"))
    assert intake_cfg.find_tesseract(str(other)) == str(other)  # nothing bundled: the setting
    tess = fake_exe(progs / "Tesseract-OCR" / ("tesseract.exe" if win else "tesseract"))
    fake_exe(progs / "Tesseract-OCR" / "tessdata" / "eng.traineddata")
    assert intake_cfg.find_tesseract(str(other)) == str(tess)  # the bundled copy wins
    assert intake_cfg.find_tesseract("-") is None
    assert intake_cfg.find_tessdata(str(tmp_path / "missing"), str(tess)) == str(tess.parent / "tessdata")
    soffice = fake_exe(progs / "LibreOffice" / "program" / ("soffice.com" if win else "soffice"))
    assert intake_cfg.find_soffice(r"C:\Users\someone\missing\soffice.com") == str(soffice)
    sz = fake_exe(progs / "7-Zip" / ("7z.exe" if win else "7z"))
    assert intake_cfg.find_sevenzip(r"C:\missing\7z.exe") == str(sz)
    monkeypatch.setenv("AX_PROGRAMS", str(tmp_path / "empty"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(intake_cfg, "LOCAL", tmp_path / "empty")
    monkeypatch.setattr(intake_cfg, "PF", [])
    assert intake_cfg.find_soffice(r"C:\Users\someone\missing\soffice.com") is None  # a missing path is not returned


def test_program_paths_saved_aside(tmp_path, monkeypatch):
    from assistant_x.intake import config as intake_cfg

    monkeypatch.setenv("AX_PROGRAMS", str(tmp_path / "empty"))  # the real programs folder would win over the setting
    path = tmp_path / "assistant_x.toml"
    path.write_text("[intake]\nheavy_mb = 40\n", encoding="utf-8")
    intake_cfg.save({"tesseract": str(tmp_path / "t.exe"), "heavy_mb": 50}, path)
    main = tomllib.loads(path.read_text(encoding="utf-8"))
    local = tomllib.loads(intake_cfg.local_path(path).read_text(encoding="utf-8"))
    assert "tesseract" not in main["intake"] and main["intake"]["heavy_mb"] == 50
    assert local == {"intake": {"tesseract": str(tmp_path / "t.exe")}}
    exe = fake_exe(tmp_path / "t.exe")
    assert intake_cfg.load(path).tesseract == str(exe)


def test_program_paths_of_the_shared_file_are_ignored(tmp_path, monkeypatch):
    """A shared assistant_x.toml (from a package, a copied workspace) never chooses which program runs here: the
    paths of programs count only in assistant_x.local.toml."""
    from assistant_x.core import config as settings
    from assistant_x.intake import config as intake_cfg

    monkeypatch.setenv("AX_PROGRAMS", str(tmp_path / "empty"))
    planted = fake_exe(tmp_path / "planted" / "ddjvu.exe")
    path = tmp_path / "assistant_x.toml"
    path.write_text(
        f'[intake]\nddjvu = "{planted.as_posix()}"\nsoffice = "{planted.as_posix()}"\nheavy_mb = 41\n', encoding="utf-8"
    )
    raw = settings.read(path)
    assert "ddjvu" not in raw["intake"] and "soffice" not in raw["intake"] and raw["intake"]["heavy_mb"] == 41
    assert intake_cfg.load(path).ddjvu != str(planted)
    intake_cfg.local_path(path).write_text(f'[intake]\nddjvu = "{planted.as_posix()}"\n', encoding="utf-8")
    assert settings.read(path)["intake"]["ddjvu"] == planted.as_posix()


def test_settings_template_has_no_paths_of_this_pc():
    import tomllib

    template = tomllib.loads((CODE / "assistant_x" / "templates" / "assistant_x.toml").read_text(encoding="utf-8"))
    assert not {"soffice", "tesseract", "tessdata", "sevenzip"} & set(template["intake"])
    for p in ("assistant_x.local.toml", ".assistant_x/db/x.sqlite", "programs/x.exe"):
        assert subprocess.run(["git", "check-ignore", "-q", p], cwd=CODE).returncode == 0
