# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The distribution (stage 7): the models of the PC (Workspace.models and its fallbacks), links never removed nor
copied over (txn.is_link, links_inside, copy_tree, with a real junction on Windows), MODELS.json and its check, the
medium of prepare-media (app, Setup.bat, packages, models), the installer taking the medium (its packages, the program
copied and installed from its wheel, the models and programs copied once, --base) and the last message naming the
folder of the skill."""

import json, os

import pytest

from assistant_x.core import txn, workspace
from assistant_x.setup import download_models as D, install

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def junction(link, target):
    """A junction link -> target (Windows), else a symbolic link."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link)


def test_models_of_the_pc(tmp_path):
    assert workspace.Workspace(tmp_path).models == workspace.machine_dir() / "models"
    (tmp_path / ".assistant_x" / "models").mkdir(parents=True)  # an older workspace keeps its own
    assert workspace.Workspace(tmp_path).models == (tmp_path / ".assistant_x" / "models").resolve()
    assert workspace.Workspace(tmp_path, {"models": "M"}).models == (tmp_path / "M").resolve()
    assert str(workspace.machine_dir()) == os.environ["AX_MACHINE_DIR"]


def test_links_are_never_followed_nor_overwritten(tmp_path):
    target = tmp_path / "frozen" / "bge-m3"
    target.mkdir(parents=True)
    (target / "weights.bin").write_bytes(b"precious")
    models = tmp_path / "models"
    models.mkdir()
    junction(models / "bge-m3", target)
    assert txn.is_link(models / "bge-m3") and not txn.is_link(target)
    assert txn.links_inside(models) == [str(models / "bge-m3")] and txn.links_inside(target) == []
    src = tmp_path / "medium" / "bge-m3"
    src.mkdir(parents=True)
    (src / "weights.bin").write_bytes(b"from the medium")
    assert txn.copy_tree(src, models / "bge-m3") is None  # a link is left as it is
    assert (target / "weights.bin").read_bytes() == b"precious"
    assert txn.copy_tree(src, models / "other") == (1, len(b"from the medium"))


def test_a_broken_environment_with_a_link_is_not_cleared(tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "Lib").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = nowhere\n", encoding="utf-8")
    frozen = tmp_path / "frozen_site_packages"
    frozen.mkdir()
    (frozen / "torch.py").write_text("# precious", encoding="utf-8")
    junction(venv / "Lib" / "frozen", frozen)
    monkeypatch.setattr(install, "check", lambda *a, **k: (False, "broken"))
    calls = []
    monkeypatch.setattr(install, "run", lambda cmd, dry, **kw: calls.append(cmd) or 0)
    with pytest.raises(install.Stop, match="holds a link"):
        install.make_venv(str(venv), dry=False)
    assert not calls and (frozen / "torch.py").exists()


def test_models_json(tmp_path):
    m = tmp_path / "models" / "bge-m3"
    (m / ".cache" / "huggingface" / "download").mkdir(parents=True)
    (m / "config.json").write_text("{}", encoding="utf-8")
    (m / ".cache" / "huggingface" / "download" / "config.json.metadata").write_text("abc123\nsha\n1\n", encoding="utf-8")
    path = D.write_manifest(str(tmp_path / "models"))
    data = json.load(open(path, encoding="utf-8"))
    entry = data["models"]["bge-m3"]
    assert entry["repo"] == "BAAI/bge-m3" and entry["revision"] == "abc123" and list(entry["files"]) == ["config.json"]
    assert D.check(str(tmp_path / "models"), data) == []
    (m / "config.json").write_text("{ }", encoding="utf-8")
    assert D.check(str(tmp_path / "models"), data) == ["bge-m3/config.json: damaged (another size)"]
    assert all(rev for _, _, rev in D.MODELS)  # the revisions of both models are pinned


def test_the_medium_of_prepare_media(tmp_path, monkeypatch):
    from assistant_x.setup import prepare_media as M

    calls = []
    monkeypatch.setattr(M, "pip", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(M, "WHEELS", str(tmp_path / "out" / "packages" / "wheels"))
    models = tmp_path / "models" / "bge-m3"
    models.mkdir(parents=True)
    (models / "config.json").write_text("{}", encoding="utf-8")
    M.medium(str(tmp_path / "out"), models=str(tmp_path / "models"))
    out = tmp_path / "out"
    assert (out / "Setup.bat").is_file() and (out / "app" / "assistant_x" / "setup" / "install.py").is_file()
    assert (out / "app" / "pyproject.toml").is_file() and not (out / "app" / "tests").exists()
    assert (out / "models" / "bge-m3" / "config.json").is_file() and (out / "models" / D.MANIFEST).is_file()
    assert calls and calls[0][0] == "wheel" and "--no-deps" in calls[0] and "--no-build-isolation" not in calls[0]
    assert "--no-index" in calls[0]  # the build tools of the medium: the wheel is built without the internet
    assert os.path.normcase(calls[0][-1]) != os.path.normcase(CODE)  # from a clean copy: no build/ of the code in it


def test_the_installer_takes_the_medium(tmp_path, monkeypatch):
    med = tmp_path / "E"
    (med / "packages" / "wheels").mkdir(parents=True)
    (med / "app").mkdir()
    (med / "models" / "bge-m3").mkdir(parents=True)
    (med / "models" / "bge-m3" / "config.json").write_text("{}", encoding="utf-8")
    D.write_manifest(str(med / "models"))
    (med / "programs" / "7-Zip").mkdir(parents=True)
    (med / "programs" / "7-Zip" / "7z.exe").write_bytes(b"MZ")
    monkeypatch.setenv("AX_MEDIUM", str(med))
    monkeypatch.setenv("AX_PROGRAMS", str(tmp_path / "programs"))
    ws = tmp_path / "ws"
    before = os.environ["AX_WORKSPACE"]
    install.use_workspace(ws)
    try:
        assert install.P.MEDIUM == str(med) and install.P.PACKS == str(med / "packages")
        assert install.pick_venv(None) == os.path.join(install.LOCAL, "venv")
        assert install.copy_models(dry=False) == []
        assert (workspace.machine_dir() / "models" / "bge-m3" / "config.json").is_file()
        install.copy_programs(dry=False)
        assert (tmp_path / "programs" / "7-Zip" / "7z.exe").is_file()
        (med / "packages" / "wheels" / "assistant_x-0.1-py3-none-any.whl").write_bytes(b"")
        from assistant_x import __version__

        (med / "packages" / "wheels" / f"assistant_x-{__version__}-py3-none-any.whl").write_bytes(b"")
        cmds = []
        monkeypatch.setattr(install, "run", lambda cmd, dry, **kw: cmds.append(cmd) or 0)
        monkeypatch.setattr(install, "CODE", str(med / "app"))
        assert install.install_self("py", offline=True, dry=False) == 0
        assert cmds[-1][-1].endswith(f"assistant_x-{__version__}-py3-none-any.whl") and "--no-index" in cmds[-1]
        assert os.path.isdir(os.path.join(install.LOCAL, "app", __version__))
        assert install.install_base("py", str(tmp_path / "x.axbase"), "own", dry=False) == []
        assert cmds[-1][2:6] == ["assistant_x.base.cli", "install", str(tmp_path / "x.axbase"), "--confirm"]
        assert cmds[-1][-2:] == ["--keep", "own"]
    finally:
        monkeypatch.undo()  # AX_MEDIUM and CODE back before the paths of the installation are made again
        install.use_workspace(before)


def test_the_last_message_names_the_folder_of_the_skill():
    text = open(os.path.join(CODE, "assistant_x", "setup", "install.py"), encoding="utf-8").read()
    assert "P.SKILL.md" not in text and "os.path.dirname(P.SKILL)" in text
    assert "install.bat" not in text and os.path.isfile(os.path.join(CODE, "Setup.bat"))


def test_setup_bat_finds_the_medium():
    text = open(os.path.join(CODE, "Setup.bat"), encoding="utf-8").read()
    assert 'set "AX_MEDIUM=%~dp0"' in text and 'set "PACKS=%~dp0packages"' in text and "-m assistant_x.setup.install" in text


def test_one_list_of_versions(tmp_path, monkeypatch):
    """setup/constraints.txt is the one list of the versions of a release: the medium's lock is made of it (torch and
    onnxruntime-directml apart), the installer takes torch and onnxruntime from it and passes it to pip online; the
    program itself is never in it, the build tools neither."""
    from assistant_x.setup import constraints as K, prepare_media as M

    pins = K.read()
    assert {"torch", "onnxruntime", "onnxruntime-directml", "numpy", "mcp", "pymupdf"} <= set(pins)
    assert not {"assistant-x", "setuptools", "wheel", "pip", "pytest", "ruff"} & set(pins)
    assert "+" not in pins["torch"][1]
    assert install.GPU_TORCH == f"torch=={pins['torch'][1]}+cu128" and install.CPU_TORCH.endswith("+cpu")
    assert install.DML_ORT == f"onnxruntime-directml=={pins['onnxruntime-directml'][1]}"
    lock, torch = M.lock_file()
    assert torch == pins["torch"][1] and f"numpy=={pins['numpy'][1]}" in lock
    assert not [p for p in lock if p.lower().startswith(("torch==", "onnxruntime-directml=="))]
    text = open(os.path.join(CODE, "assistant_x", "setup", "install.py"), encoding="utf-8").read()
    assert '"-c", K.PATH' in text and "2.11.0" not in text and "1.31.0" not in text
    assert not os.path.exists(os.path.join(CODE, "requirements", "requirements.lock"))  # one list only
    other = tmp_path / "c.txt"
    other.write_text("# x\nFoo_Bar==1.0  # why\n", encoding="utf-8")
    assert K.read(str(other)) == {"foo-bar": ("Foo_Bar", "1.0")} and K.pin("foo.bar", str(other)) == "1.0"
    with pytest.raises(SystemExit):
        K.pin("torch", str(other))


def test_a_trial_run_makes_no_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(install.P, "INBOX", str(tmp_path / "ws" / "inbox"))
    assert install.check_intake("py", dry=True) == [] and not (tmp_path / "ws").exists()


def test_the_wheels_of_the_video_cards(tmp_path, monkeypatch):
    """A medium carries torch for NVIDIA cards (the CUDA build install.py installs) and onnxruntime-directml, in the
    folders install.py looks into."""
    from assistant_x.setup import prepare_media as M

    calls = []
    monkeypatch.setattr(M, "pip", lambda *a, **k: calls.append(a))
    assert M.gpu_wheels(str(tmp_path / "packages")) == [install.GPU_TORCH, install.DML_ORT]
    gpu, dml = calls
    assert install.GPU_TORCH in gpu and M.torch_cuda_index() in gpu and str(tmp_path / "packages" / "wheels_gpu") in gpu
    assert install.DML_ORT in dml and str(tmp_path / "packages" / "wheels_dml") in dml
    assert M.torch_cuda_index().endswith("/" + install.GPU_TORCH.split("+")[1])  # one constant for both sides
    calls.clear()
    assert M.gpu_wheels(str(tmp_path / "p2"), cuda=False) == [install.DML_ORT] and len(calls) == 1
    M.readme(str(tmp_path), cuda=True, dml=False)
    text = (tmp_path / "README.txt").read_text(encoding="utf-8")
    assert install.GPU_TORCH in text and "NOT on this medium" in text and str(install.MIN_DRIVER) in text
    assert "AGPL-3.0-or-later" in text and "complete source" in text and M.REPOSITORY in text  # what AGPL users need


def test_the_licenses_name_the_builds_of_the_cards(tmp_path, monkeypatch):
    from assistant_x.setup import prepare_media as M

    monkeypatch.setattr(M, "PACKS", str(tmp_path))
    M.third_party(["numpy==2.0.0"], "2.11.0", [install.GPU_TORCH, install.DML_ORT])
    text = (tmp_path / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
    assert "the CUDA build" in text and "onnxruntime" in text.lower() and install.DML_ORT.split("==")[1] in text


def test_a_medium_made_again_keeps_its_programs(tmp_path, monkeypatch):
    from assistant_x.setup import prepare_media as M

    monkeypatch.setattr(M, "pip", lambda *a, **k: None)
    monkeypatch.setattr(M, "build_python", lambda: "python")
    monkeypatch.setattr(M, "WHEELS", str(tmp_path / "out" / "packages" / "wheels"))
    (tmp_path / "out" / "programs" / "7-Zip").mkdir(parents=True)
    ran, real = [], M.proc.run

    def run(*a, **k):  # git ls-files runs; collect_programs would be recorded
        ran.append(a)
        return real(*a, **k) if "git" in str(a[0][:1]) else None

    monkeypatch.setattr(M.proc, "run", run)
    M.medium(str(tmp_path / "out"), no_models=True, programs=True)
    collected = [a for a in ran if "collect_programs" in str(a)]
    assert all("--versions" in a[0] for a in collected) and (tmp_path / "out" / "programs" / "7-Zip").is_dir()


def test_the_sources_of_the_copyleft_programs(tmp_path, monkeypatch):
    """prepare-media puts the source archives of DjVuLibre and 7-Zip on the medium, each checked by its sha256: a wrong
    download is not kept, a version without a pinned archive stops; NOTICE and the license texts name them."""
    import hashlib
    from assistant_x.setup import medium as MD, prepare_media as M

    data = {"DjVuLibre": b"djvulibre source", "7-Zip": b"7-zip source"}
    pins = {
        name: {
            "9.9": {
                "url": f"https://example.org/{name}.tar",
                "file": f"{name}.tar",
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        }
        for name, body in data.items()
    }
    monkeypatch.setattr(MD, "SOURCES", pins)
    monkeypatch.setattr(MD, "bundled", lambda programs: {"DjVuLibre": "9.9", "7-Zip": "9.9"})
    served = dict(data)

    def get(url, path):
        with open(path, "wb") as f:
            f.write(served[url.rsplit("/", 1)[1][:-4]])

    monkeypatch.setattr(M.urllib.request, "urlretrieve", get)
    programs = tmp_path / "programs"
    assert M.program_sources(str(programs)) == {"DjVuLibre": "9.9", "7-Zip": "9.9"}
    assert (programs / "sources" / "DjVuLibre.tar").read_bytes() == data["DjVuLibre"]
    listing = (programs / "sources" / "SOURCES.txt").read_text(encoding="utf-8-sig")
    assert "GPL-2.0-or-later" in listing and "7-Zip.tar" in listing
    served["7-Zip"] = b"tampered"
    (programs / "sources" / "7-Zip.tar").unlink()
    with pytest.raises(SystemExit, match="sha256"):
        M.program_sources(str(programs))
    assert not list((programs / "sources").glob("7-Zip.tar*"))
    monkeypatch.setattr(MD, "bundled", lambda programs: {"7-Zip": "1.0"})
    with pytest.raises(SystemExit, match="No pinned source archive"):
        M.program_sources(str(programs))
    notice = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "NOTICE"), encoding="utf-8").read()
    assert "DjVuLibre" in notice and "GPL-2.0-or-later" in notice
    assert MD.source_line("LibreOffice", "26.8.1").endswith("libreoffice/src/26.8.1/")
    assert set(MD.SOURCES) == {"DjVuLibre", "7-Zip"} and all(
        len(v["sha256"]) == 64 for x in MD.SOURCES.values() for v in x.values()
    )


def test_the_license_texts_go_into_the_wheel():
    import tomllib

    data = tomllib.loads(
        open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "pyproject.toml"), encoding="utf-8").read()
    )
    assert {"LICENSE", "LICENSES/*", "NOTICE"} <= set(data["project"]["license-files"])


def test_directml_is_chosen_with_the_onnx_models_of_the_medium(tmp_path, monkeypatch):
    """A first install from a medium: the ONNX export lies on the medium (models/onnx), not yet on the PC; the device
    is chosen after the models are copied and DirectML is chosen; the layout names are one module's."""
    from assistant_x.search import onnx_models
    from assistant_x.setup import medium as ML

    med = tmp_path / "E"
    (med / ML.PACKAGES_DIR / ML.WHEELS_DML).mkdir(parents=True)
    (med / ML.PACKAGES_DIR / ML.WHEELS_DML / "onnxruntime_directml-1.24.4-cp311-cp311-win_amd64.whl").write_bytes(b"")
    (med / ML.APP_DIR).mkdir()
    onnx = med.joinpath(ML.MODELS_DIR, *ML.ONNX_EMBEDDER)
    onnx.parent.mkdir(parents=True)
    onnx.write_bytes(b"onnx")
    monkeypatch.setenv("AX_MEDIUM", str(med))
    monkeypatch.setattr(onnx_models, "adapters", lambda: [(0, "Radeon RX", 0x1002, 16.0)])
    before = os.environ["AX_WORKSPACE"]
    install.use_workspace(tmp_path / "ws")
    try:
        assert not os.path.exists(os.path.join(install.P.MODELS, *ML.ONNX_EMBEDDER))
        assert install.onnx_models_here() and install.dml_or_cpu(offline=True) == "dml"
        onnx.unlink()
        assert install.dml_or_cpu(offline=True) == "cpu"
    finally:
        monkeypatch.undo()
        install.use_workspace(before)
    text = open(os.path.join(CODE, "assistant_x", "setup", "install.py"), encoding="utf-8").read()
    main = text[text.index("def main(") :]
    assert main.index("copy_models(dry)") < main.index("choose_device(")  # the models before the device
    assert ".assistant_x\\packages" not in text and '"wheels_gpu"' not in text


def test_download_models_exports_onnx(tmp_path, monkeypatch):
    from assistant_x.search import onnx_models

    done = []
    monkeypatch.setattr(onnx_models, "export", lambda: done.append((onnx_models.MODELS, onnx_models.ONNX_DIR)))
    import sys, types

    monkeypatch.setitem(sys.modules, "onnx", types.ModuleType("onnx"))
    assert D.export_onnx(str(tmp_path)) and done == [(str(tmp_path), os.path.join(str(tmp_path), "onnx"))]
    assert onnx_models.MODELS is None  # put back
    monkeypatch.setitem(sys.modules, "onnx", None)  # not installed
    assert not D.export_onnx(str(tmp_path / "other"))


def test_downloads_are_checked_before_they_take_their_name(tmp_path, monkeypatch):
    """A download goes to .part, is checked against its pinned sha256 and only then renamed; a changed one is removed;
    the lock of a medium carries the sha256 of every wheel (pip --require-hashes), the video card wheels too; the
    Python installer must be signed by the PSF and is named in SHA256SUMS.txt, which Setup.bat checks."""
    import hashlib
    from assistant_x.setup import downloads, prepare_media as M, medium as ML

    body = b"traineddata"
    monkeypatch.setattr(downloads.urllib.request, "urlretrieve", lambda url, path: open(path, "wb").write(body))
    good = hashlib.sha256(body).hexdigest()
    downloads.fetch("https://x/eng", good, tmp_path / "eng.traineddata", say=lambda *_: None)
    assert (tmp_path / "eng.traineddata").read_bytes() == body
    with pytest.raises(SystemExit, match="sha256"):
        downloads.fetch("https://x/rus", "0" * 64, tmp_path / "rus.traineddata", say=lambda *_: None)
    assert not list(tmp_path.glob("rus.traineddata*"))
    assert set(downloads.TESSDATA) == {"rus", "eng", "osd"}
    wheels, gpu = tmp_path / "wheels", tmp_path / "wheels_gpu"
    wheels.mkdir(), gpu.mkdir()
    (wheels / "numpy-2.4.6-cp311-cp311-win_amd64.whl").write_bytes(b"np")
    (wheels / "torch-2.11.0+cpu-cp311-cp311-win_amd64.whl").write_bytes(b"cpu")
    (gpu / "torch-2.11.0+cu128-cp311-cp311-win_amd64.whl").write_bytes(b"gpu")
    lock = tmp_path / "requirements-lock.txt"
    lock.write_text("numpy==2.4.6\ntorch==2.11.0\n", encoding="utf-8")
    M.hashed_lock(str(lock), str(wheels), [(str(gpu), "torch==2.11.0+cu128"), (str(tmp_path / "none"), "x==1")])
    text = lock.read_text(encoding="utf-8")
    assert f"numpy==2.4.6 --hash=sha256:{hashlib.sha256(b'np').hexdigest()}" in text
    assert f"torch==2.11.0 --hash=sha256:{hashlib.sha256(b'cpu').hexdigest()}" in text
    assert install.has_hashes(str(lock)) and install.hashed(str(gpu), "torch") == [
        "--require-hashes",
        "-r",
        str(gpu / ML.HASHED_REQ),
    ]
    assert install.hashed(str(tmp_path / "none"), "x==1") == ["x==1"]  # only with --allow-unverified
    lock.write_text("scipy==1.17.1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not whole"):
        M.hashed_lock(str(lock), str(wheels))
    packs = tmp_path / "packs"
    packs.mkdir()
    monkeypatch.setattr(M, "PACKS", str(packs))
    monkeypatch.setattr(M.os, "name", "nt")
    monkeypatch.setattr(M.urllib.request, "urlretrieve", lambda url, path: open(path, "wb").write(b"exe"))
    monkeypatch.setattr(downloads, "signed_by", lambda path, who: "signature NotSigned of nobody")
    with pytest.raises(SystemExit, match="Python Software Foundation"):
        M.python_installer()
    assert not os.listdir(packs)
    monkeypatch.setattr(downloads, "signed_by", lambda path, who: "")
    M.python_installer()
    exe = [n for n in os.listdir(packs) if n.endswith(".exe")]
    downloads.sums(str(packs), exe)
    assert exe and downloads.check_sums(str(packs)) == []
    (packs / exe[0]).write_bytes(b"changed")
    assert downloads.check_sums(str(packs)) == [f"{exe[0]}: another sha256"]
    bat = open(os.path.join(CODE, "Setup.bat"), encoding="utf-8").read()
    assert "certutil -hashfile" in bat and "SHA256SUMS.txt" in bat


def test_a_model_copy_is_whole_or_made_again(tmp_path, monkeypatch):
    """A model folder is copied to <name>.part and renamed when whole; on the next run a folder there already is
    checked by its sizes against MODELS.json: one cut by a power failure is copied again, a stale .part too; a linked
    one is never touched (only told)."""
    med = tmp_path / "E"
    (med / "packages" / "wheels").mkdir(parents=True)
    (med / "app").mkdir()
    for name in ("bge-m3", "bge-reranker-v2-m3"):
        (med / "models" / name).mkdir(parents=True)
        (med / "models" / name / "model.safetensors").write_bytes(b"weights of " + name.encode())
    D.write_manifest(str(med / "models"))
    monkeypatch.setenv("AX_MEDIUM", str(med))
    monkeypatch.setenv("AX_MACHINE_DIR", str(tmp_path / "pc"))
    before = os.environ["AX_WORKSPACE"]
    install.use_workspace(tmp_path / "ws")
    try:
        models = workspace.machine_dir() / "models"
        (models / "bge-m3").mkdir(parents=True)
        (models / "bge-m3" / "model.safetensors").write_bytes(b"weig")  # cut by a power failure
        (models / "bge-reranker-v2-m3.part").mkdir()
        (models / "bge-reranker-v2-m3.part" / "half").write_bytes(b"x")
        assert install.copy_models(dry=False) == []
        for name in ("bge-m3", "bge-reranker-v2-m3"):
            assert (models / name / "model.safetensors").read_bytes() == b"weights of " + name.encode()
        assert not list(models.glob("*.part")) and not list(models.glob("*.old"))
        assert install.copy_models(dry=False) == []  # whole now: left as they are
        frozen = tmp_path / "frozen" / "bge-m3"
        frozen.mkdir(parents=True)
        (frozen / "model.safetensors").write_bytes(b"precious")
        import shutil

        shutil.rmtree(models / "bge-m3")
        junction(models / "bge-m3", frozen)
        problems = install.copy_models(dry=False)
        assert problems and "a link" in problems[0] and (frozen / "model.safetensors").read_bytes() == b"precious"
    finally:
        monkeypatch.undo()
        install.use_workspace(before)


def test_installer_housekeeping(tmp_path, monkeypatch):
    r"""Only the last three backups of the settings of Claude Desktop stay; app\<version> is copied again when the
    wheel of the medium is another build of the same version, and left alone when it is the same."""
    from assistant_x import clients

    prefix = "claude_desktop_config.backup-"
    for k in range(6):
        (tmp_path / f"{prefix}2026-10-2{k}_120000.json").write_text("{}", encoding="utf-8")
    (tmp_path / "claude_desktop_config.json").write_text("{}", encoding="utf-8")
    clients.prune(tmp_path / "claude_desktop_config.json")
    left = sorted(f.name for f in tmp_path.iterdir() if f.name.startswith(prefix))
    assert left == [f"{prefix}2026-10-2{k}_120000.json" for k in (3, 4, 5)]
    assert (tmp_path / "claude_desktop_config.json").exists()
    code = tmp_path / "app_src"
    (code / "assistant_x").mkdir(parents=True)
    (code / "assistant_x" / "x.py").write_text("one", encoding="utf-8")
    monkeypatch.setattr(install, "CODE", str(code))
    wheel = tmp_path / "assistant_x-0.1-py3-none-any.whl"
    wheel.write_bytes(b"build 1")
    dst = tmp_path / "app" / "0.1"
    install.refresh_app(str(dst), str(wheel))
    assert (dst / "assistant_x" / "x.py").read_text(encoding="utf-8") == "one"
    (code / "assistant_x" / "x.py").write_text("two", encoding="utf-8")
    install.refresh_app(str(dst), str(wheel))  # the same build: left as it is
    assert (dst / "assistant_x" / "x.py").read_text(encoding="utf-8") == "one"
    wheel.write_bytes(b"build 2")
    install.refresh_app(str(dst), str(wheel))  # another build of 0.1: copied again
    assert (dst / "assistant_x" / "x.py").read_text(encoding="utf-8") == "two"


def test_collect_programs_is_a_module_and_sums_what_it_copies(tmp_path):
    """collect_programs runs from main(argv) (importing it does nothing); --versions writes VERSIONS.txt and
    SHA256SUMS.txt with the sha256 of every file of the programs (the source archives aside)."""
    import hashlib
    from assistant_x.setup import collect_programs as CP, downloads

    (tmp_path / "7-Zip").mkdir()
    (tmp_path / "7-Zip" / "7z.exe").write_bytes(b"MZ seven")
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "7z-src.tar.xz").write_bytes(b"source")
    assert CP.main(["--versions", "--dst", str(tmp_path)]) == 0
    sums = (tmp_path / CP.SUMS).read_text(encoding="utf-8")
    assert f"{hashlib.sha256(b'MZ seven').hexdigest()} *7-Zip/7z.exe" in sums and "sources" not in sums
    assert "SHA256SUMS.txt" in (tmp_path / "VERSIONS.txt").read_text(encoding="utf-8-sig")
    (tmp_path / "7-Zip" / "7z.exe").write_bytes(b"changed")
    assert CP.SUMS == downloads.SUMS and hashlib.sha256(b"changed").hexdigest() not in sums


def test_the_package_metadata():
    """PEP 639: an SPDX license expression with the license files, no License classifier beside it; the systems the
    program runs on."""
    import tomllib

    data = tomllib.loads(open(os.path.join(CODE, "pyproject.toml"), encoding="utf-8").read())
    project = data["project"]
    assert project["license"] == "AGPL-3.0-or-later" and not [c for c in project["classifiers"] if c.startswith("License")]
    assert {"Operating System :: Microsoft :: Windows", "Operating System :: POSIX :: Linux"} <= set(project["classifiers"])
    assert data["build-system"]["requires"] == ["setuptools>=77"]


def _a_whole_medium(tmp_path, monkeypatch):
    """A medium as prepare-media makes it, without the internet: the program (app, Setup.bat, the wheel of this code),
    a wheel file per version of constraints.txt, the hashed lock and SHA256SUMS.txt."""
    import zipfile
    from assistant_x import __version__
    from assistant_x.setup import downloads, medium as ML, prepare_media as M

    out = tmp_path / "medium"
    wheels = out / ML.PACKAGES_DIR / ML.WHEELS
    wheels.mkdir(parents=True)

    def pip(*args, **k):  # the wheel of the program from the files of this code
        with zipfile.ZipFile(wheels / f"assistant_x-{__version__}-py3-none-any.whl", "w") as z:
            for f in M.app_files(CODE):
                if f.startswith("assistant_x/"):
                    z.write(os.path.join(CODE, *f.split("/")), f)

    monkeypatch.setattr(M, "pip", pip)
    monkeypatch.setattr(M, "build_python", lambda: "python")
    monkeypatch.setattr(M, "WHEELS", str(wheels))
    M.medium(str(out), no_models=True)
    pins, torch = M.lock_file()
    for pin in pins + [f"torch=={torch}"]:
        name, ver = pin.split("==")
        (wheels / f"{M.norm(name)}-{ver}-py3-none-any.whl").write_bytes(pin.encode())
    lock = out / ML.PACKAGES_DIR / ML.LOCK_FILE
    lock.write_text("\n".join(pins + [f"torch=={torch}"]) + "\n", encoding="utf-8")
    M.hashed_lock(str(lock), str(wheels))
    (out / ML.PACKAGES_DIR / "python-3.11.9-amd64.exe").write_bytes(b"MZ")
    downloads.sums(
        str(out / ML.PACKAGES_DIR), ["python-3.11.9-amd64.exe", f"wheels/assistant_x-{__version__}-py3-none-any.whl"]
    )
    return out


def test_prepare_media_check_tells_a_whole_medium_from_a_stale_one(tmp_path, monkeypatch):
    """prepare-media --check: a medium made from this code is in order; a changed file of app, a file the code no
    longer has, a wheel changed after the lock and a lock without hashes are each reported."""
    from assistant_x.setup import medium as ML, prepare_media as M

    out = _a_whole_medium(tmp_path, monkeypatch)
    assert M.check(str(out)) == []
    assert M.main(["--check", str(out)]) == 0
    (out / "app" / "README.md").write_text("an older README\n", encoding="utf-8")
    (out / "app" / "assistant_x" / "gone.py").write_text("", encoding="utf-8")
    wheel = next((out / "packages" / "wheels").glob("numpy-*.whl"))
    wheel.write_bytes(b"changed")
    problems = M.check(str(out))
    assert "app/README.md: not the file of this code" in problems
    assert "app/assistant_x/gone.py: not a file of this code" in problems
    assert any("no wheel of numpy==" in p for p in problems)
    lock = out / ML.PACKAGES_DIR / ML.LOCK_FILE
    lock.write_text("\n".join(x.split()[0] for x in lock.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    assert any("no sha256 for" in p for p in M.check(str(out))) and M.main(["--check", str(out)]) == 1


def test_the_installer_refuses_a_medium_it_cannot_check(tmp_path, monkeypatch):
    """A medium whose lock carries no sha256 or without SHA256SUMS.txt is refused, nothing installed, unless
    --allow-unverified; a whole medium passes."""
    import subprocess, sys
    from assistant_x.setup import downloads, medium as ML

    out = _a_whole_medium(tmp_path, monkeypatch)
    monkeypatch.setenv("AX_MEDIUM", str(out))
    before = os.environ["AX_WORKSPACE"]
    install.use_workspace(tmp_path / "ws")
    try:
        assert install.unverified() == []
        (out / ML.PACKAGES_DIR / downloads.SUMS).unlink()
        assert any("SHA256SUMS.txt" in p for p in install.unverified())
        lock = out / ML.PACKAGES_DIR / ML.LOCK_FILE
        lock.write_text("numpy==2.4.6\n", encoding="utf-8")
        assert any("carries no sha256" in p for p in install.unverified())
    finally:
        monkeypatch.undo()
        install.use_workspace(before)
    env = dict(os.environ, AX_MEDIUM=str(out), PYTHONUTF8="1", AX_YES="1")
    cmd = [sys.executable, "-m", "assistant_x.setup.install", "--dry-run", "--no-register", "--yes"]
    cmd += ["--workspace", str(tmp_path / "ws2")]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, cwd=CODE, timeout=300)
    assert p.returncode == 1 and "cannot be checked" in p.stdout and "--allow-unverified" in p.stdout
    p = subprocess.run(
        cmd + ["--allow-unverified"], capture_output=True, text=True, encoding="utf-8", env=env, cwd=CODE, timeout=300
    )
    assert "WARNING, not checked" in p.stdout and "cannot be checked" not in p.stdout
