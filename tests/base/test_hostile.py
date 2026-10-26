# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hostile base packages: a package is data from someone else. A manifest whose id or version leaves the work
folder, a profile or card languages that would write TOML of their own, card paths that name files outside the
workspace — each is refused by inspect, install and update, and nothing in the workspace (or beside it) changes.
The packages are the package of library A unpacked into a folder package, changed, and their checksums made again
(a damaged checksum would be refused for another reason)."""

import hashlib, json, os, shutil, zipfile

import pytest

from assistant_x.base import export as X, inspection as I, install as B, package as P, update as U
from assistant_x.core import config as settings
from assistant_x.core.common import load_config
from tests.base import libraries
from tests.base.test_install import empty, state
from tests.search.conftest import build, make_library, write
from tests.search.fake_embedder import embed


def say(_):
    pass


@pytest.fixture(scope="module")
def package_a(tmp_path_factory):
    base = tmp_path_factory.mktemp("hostile")
    a = make_library(str(base / "A"))
    build(a)
    embed(a)
    X.export(load_config(a), settings.load(a)[1], str(base / "a.axbase"), "test-a", "1.0", say=say)
    return str(base / "a.axbase")


def unpacked(pkg, out):
    """The package as a folder package at out."""
    with zipfile.ZipFile(pkg) as z:
        z.extractall(out)
    return str(out)


def reseal(folder):
    """CHECKSUMS.sha256 made again for every file of a folder package."""
    lines = []
    for dp, _, fns in os.walk(folder):
        for f in fns:
            rel = os.path.relpath(os.path.join(dp, f), folder).replace(os.sep, "/")
            if rel != P.CHECKSUMS:
                lines.append(f"{hashlib.sha256(open(os.path.join(dp, f), 'rb').read()).hexdigest()}  {rel}")
    write(os.path.join(folder, P.CHECKSUMS), "\n".join(sorted(lines)) + "\n")
    return folder


def with_manifest(pkg, out, **changes):
    folder = unpacked(pkg, out)
    p = os.path.join(folder, P.MANIFEST)
    man = json.load(open(p, encoding="utf-8"))
    man.update(changes)
    write(p, json.dumps(man, ensure_ascii=False, indent=1))
    return reseal(folder)


def with_card(pkg, out, code, **file_changes):
    folder = unpacked(pkg, out)
    p = os.path.join(folder, "cards", f"{code}.json")
    card = json.load(open(p, encoding="utf-8"))
    card["file"].update(file_changes)
    write(p, json.dumps(card, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return reseal(folder)


def outside(tmp_path):
    """Every file under tmp_path but inside the workspace folder ws or the package folders: what a package could
    have written beside the workspace."""
    out = set()
    for dp, dns, fns in os.walk(tmp_path):
        dns[:] = [d for d in dns if d not in ("ws", "pkg")]
        out |= {os.path.relpath(os.path.join(dp, f), tmp_path) for f in fns}
    return out


TOML_INJECTION = 'general"\n[intake]\nddjvu = "C:/planted/tool.exe"\n#'


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "x/../../../../ESCAPED"},
        {"id": "..\\..\\ESCAPED"},
        {"id": "Upper-Case"},
        {"id": ""},
        {"id": 5},
        {"version": "1.0/../../../ESCAPED"},
        {"version": "1\n[intake]"},
        {"version": ""},
        {"profile": TOML_INJECTION},
        {"profile": "no-such-profile"},
        {"card_languages": ["ru", 'xx"]\n[intake]\nsoffice = "evil.exe"\n#']},
        {"card_languages": "ru"},
        {"codes": "everything"},
        {"embed": {"fingerprint": "../x", "dim": 1024, "rows": 1}},
        {"docs": [{"code": "../N-00001"}]},
        {"name": {"en": ["not", "text"]}},
    ],
)
def test_a_hostile_manifest_is_refused(package_a, tmp_path, changes):
    pkg = with_manifest(package_a, tmp_path / "pkg", **changes)
    path = empty(str(tmp_path / "ws"))
    toml = open(path, encoding="utf-8").read()
    before, beside = state(str(tmp_path / "ws")), outside(tmp_path)
    with pytest.raises(P.PackageError, match="refused"):
        I.inspect(load_config(path), settings.load(path)[1], pkg)
    with pytest.raises(P.PackageError):
        B.install(pkg, confirm=True, keep="package", config=path, say=say)
    with pytest.raises(SystemExit):
        B.main([pkg, "--confirm", "--config", path])
    with pytest.raises(P.PackageError):
        U.update(pkg, confirm=True, config=path, say=say)
    assert open(path, encoding="utf-8").read() == toml and "intake" not in settings.read(path)
    assert state(str(tmp_path / "ws")) == before and outside(tmp_path) == beside
    assert not os.path.exists(os.path.join(tmp_path, "ws", ".assistant_x", "w"))


def test_remove_takes_only_an_id(tmp_path):
    path = empty(str(tmp_path / "ws"))
    assert U.remove("../../x", confirm=True, config=path, say=say) == 1
    assert not os.path.exists(os.path.join(tmp_path, "ws", ".assistant_x", "w"))


def test_the_adopted_settings_are_escaped(tmp_path):
    """adopt() writes the values of a manifest as TOML strings: whatever they hold, no key of their own; a profile or
    a language this program has not stops it."""
    path = empty(str(tmp_path / "ws"))
    w = settings.load(path)[0]
    B.adopt(w, "oil-gas-ru", ["ru", "en"])
    assert settings.read(path)["profile"] == "oil-gas-ru"
    assert settings.read(path)["documents"]["languages"] == ["ru", "en"]
    for profile, langs in ((TOML_INJECTION, ["en"]), ("general", ['ru"]\n[intake]\nddjvu = "x"\n#'])):
        with pytest.raises(B.Stop):
            B.adopt(w, profile, langs)
    assert "intake" not in settings.read(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pdf_copy", "../../../../VICTIM.txt"),
        ("library", "library/../../../VICTIM.txt"),
        ("text", "index/texts/../../../VICTIM.txt"),
        ("library", "C:/VICTIM.txt"),
        ("pdf_copy", "library/a:stream"),
        ("library", "inbox/x.pdf"),
    ],
)
def test_card_paths_outside_the_workspace_are_refused(package_a, tmp_path, field, value):
    victim = tmp_path / "VICTIM.txt"
    victim.write_text("the user's file", encoding="utf-8")
    pkg = with_card(package_a, tmp_path / "pkg", "N-00002", **{field: value})
    root = str(tmp_path / "ws")
    path = libraries.make_b(root)
    before, beside = state(root), outside(tmp_path)
    report = I.inspect(load_config(path), settings.load(path)[1], pkg, keep="package")
    assert not report["ok"] and any("unsafe path in the package card N-00002" in p for p in report["problems"])
    assert B.install(pkg, confirm=True, keep="package", config=path, say=say) == 1
    assert state(root) == before and outside(tmp_path) == beside
    assert victim.read_text(encoding="utf-8") == "the user's file"


def test_an_update_with_card_paths_outside_is_refused(package_a, tmp_path):
    root = str(tmp_path / "ws")
    path = empty(root)
    assert B.install(package_a, confirm=True, config=path, say=say) == 0
    victim = tmp_path / "VICTIM.txt"
    victim.write_text("the user's file", encoding="utf-8")
    pkg = with_card(package_a, tmp_path / "pkg", "N-00002", pdf_copy="../../../VICTIM.txt")
    man = os.path.join(pkg, P.MANIFEST)
    write(man, json.dumps(dict(json.load(open(man, encoding="utf-8")), version="2.0"), indent=1))
    reseal(pkg)
    before = state(root)
    assert U.update(pkg, confirm=True, config=path, say=say) == 1
    assert state(root) == before and victim.read_text(encoding="utf-8") == "the user's file"


def test_no_move_leaves_the_workspace(tmp_path):
    root = str(tmp_path / "ws")
    os.makedirs(root)
    assert B.within(root, "library/a.pdf") == os.path.join(root, "library", "a.pdf")
    for rel in ("../x", "library/../../x", "C:/x", "/x", "library/a:b", "library\\..\\..\\x"):
        with pytest.raises(B.Stop):
            B.within(root, rel)
    if hasattr(os, "symlink"):
        try:
            os.symlink(str(tmp_path), os.path.join(root, "link"), target_is_directory=True)
        except OSError:
            return  # no right to make links here
        with pytest.raises(B.Stop):
            B.within(root, "link/x")
    shutil.rmtree(root)


def with_vectors(pkg, out, change):
    """The package with its vectors changed: change(info, keys, vecs) -> (info, keys bytes, vecs array)."""
    import numpy as np

    folder = unpacked(pkg, out)
    d = os.path.join(folder, "vectors")
    info = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    keys = open(os.path.join(d, "keys.bin"), "rb").read()
    vecs = np.fromfile(os.path.join(d, "vectors.f16"), dtype=np.float16).reshape(-1, info["dim"])
    info, keys, vecs = change(info, keys, vecs)
    write(os.path.join(d, "meta.json"), json.dumps(info, indent=1))
    open(os.path.join(d, "keys.bin"), "wb").write(keys)
    open(os.path.join(d, "vectors.f16"), "wb").write(np.asarray(vecs, dtype=np.float16).tobytes())
    man = os.path.join(folder, P.MANIFEST)
    write(man, json.dumps(dict(json.load(open(man, encoding="utf-8")), embed=info), indent=1))
    return reseal(folder)


def _dim(info, keys, vecs):
    import numpy as np

    return dict(info, dim=info["dim"] * 2), keys, np.concatenate([vecs, vecs], axis=1) / np.sqrt(2)


def _rows(info, keys, vecs):
    return dict(info, rows=info["rows"] + 3), keys, vecs


def _norm(info, keys, vecs):
    return info, keys, vecs * 2


def _nan(info, keys, vecs):
    vecs = vecs.copy()
    vecs[0, 0] = float("nan")
    return info, keys, vecs


def _twice(info, keys, vecs):
    return info, keys[:16] + keys[16:-16] + keys[:16], vecs


@pytest.mark.parametrize(
    "change,why", [(_dim, "dimension"), (_rows, "keys need"), (_norm, "length 1"), (_nan, "length 1"), (_twice, "twice")]
)
def test_package_vectors_that_do_not_hold_are_refused(package_a, tmp_path, change, why):
    from assistant_x.search import vector_cache as V

    pkg = with_vectors(package_a, tmp_path / "pkg", change)
    root = str(tmp_path / "ws")
    path = empty(root)
    os.makedirs(os.path.join(root, ".assistant_x", "vector_cache"), exist_ok=True)
    V.Cache(load_config(path)).add([b"k" * V.KEY_BYTES], [[1.0] + [0.0] * 63])  # the model here: dimension 64
    report = I.inspect(load_config(path), settings.load(path)[1], pkg)
    assert not report["ok"] and any(p.startswith("package vectors:") and why in p for p in report["problems"]), report[
        "problems"
    ]
    before = state(root)
    assert B.install(pkg, confirm=True, config=path, say=say) == 1 and state(root) == before


def test_vectors_of_other_fragments_are_left_out(package_a, tmp_path):
    """A package whose vectors carry the keys of the user's own fragments (content-addressed keys of public texts)
    never sets their vectors: only keys of the package's own documents are taken."""
    import numpy as np
    from assistant_x.core.common import connect
    from assistant_x.search import embed as E, vector_cache as V

    root = str(tmp_path / "ws")
    path = libraries.make_b(root)
    build(path)
    cfg = load_config(path)
    con = connect(cfg["db"], readonly=True)
    theirs = E.keys_of(E.fragments(con, "1=1"), V.fingerprint(cfg), False)[:3]
    con.close()
    planted = np.eye(64, dtype=np.float32)[:3]

    def change(info, keys, vecs):
        return info, b"".join(theirs) + keys[3 * V.KEY_BYTES :], np.concatenate([planted, vecs[3:]])

    pkg = with_vectors(package_a, tmp_path / "pkg", change)
    assert B.install(pkg, confirm=True, keep="package", config=path, say=say) == 0
    got = V.Cache(load_config(path)).get(theirs)
    assert all(not np.allclose(got[k], planted[i]) for i, k in enumerate(theirs) if k in got)
    report = [f for f in os.listdir(os.path.join(root, "reports")) if f.startswith("base_install_")]
    assert "not of fragments of its own documents" in open(os.path.join(root, "reports", report[0]), encoding="utf-8").read()


def test_vectors_that_the_model_here_does_not_give_are_dropped(package_a, tmp_path):
    """With the model on this PC a sample of the package's vectors is encoded again: whole vectors of other
    fragments (the rows shuffled) fail it and none of the package's vectors is used; the right ones pass."""
    import numpy as np
    from tests.search.fake_embedder import fake_models

    def shuffle(info, keys, vecs):
        return info, keys, np.roll(vecs, 1, axis=0)

    for name, pkg, used in (("good", package_a, True), ("bad", with_vectors(package_a, tmp_path / "pkg", shuffle), False)):
        root = str(tmp_path / name)
        path = empty(root)
        with open(path, "a", encoding="utf-8") as f:  # the models of this workspace, not of the PC of the tests
            f.write('\n[paths]\nmodels = "models"\n')
        model = load_config(path)["embed_model"]
        assert model.startswith(root)
        os.makedirs(model, exist_ok=True)
        with fake_models():
            assert B.install(pkg, confirm=True, config=path, say=say) == 0
        report = [f for f in os.listdir(os.path.join(root, "reports")) if f.startswith("base_install_")]
        text = open(os.path.join(root, "reports", report[0]), encoding="utf-8").read()
        assert ("encoded again, cosine" in text) == used and ("rejected" in text) == (not used), text


def test_one_poisoned_vector_of_a_small_package_is_caught(package_a, tmp_path):
    """The sample grows with the package (vectors.sample_size): every vector of a small package is encoded again, so a
    single vector of another text among them is found and none of the package's vectors is used."""
    import numpy as np
    from assistant_x.base import vectors as BV
    from tests.search.fake_embedder import fake_models

    assert BV.sample_size(10) == 10 and BV.sample_size(111) == 32 and BV.sample_size(2000) == 100
    assert BV.sample_size(100_000) == 256

    def poison_one(info, keys, vecs):
        out = vecs.copy()
        v = np.random.default_rng(1).standard_normal(out.shape[1]).astype(np.float32)
        out[len(out) // 2] = (v / np.linalg.norm(v)).astype(out.dtype)
        return info, keys, out

    pkg = with_vectors(package_a, tmp_path / "pkg", poison_one)
    root = str(tmp_path / "ws")
    path = empty(root)
    with open(path, "a", encoding="utf-8") as f:
        f.write('\n[paths]\nmodels = "models"\n')
    os.makedirs(load_config(path)["embed_model"], exist_ok=True)
    with fake_models():
        assert B.install(pkg, confirm=True, config=path, say=say) == 0
    report = [f for f in os.listdir(os.path.join(root, "reports")) if f.startswith("base_install_")]
    assert "rejected" in open(os.path.join(root, "reports", report[0]), encoding="utf-8").read()
