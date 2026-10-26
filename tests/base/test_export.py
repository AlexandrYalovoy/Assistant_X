# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assistant-x base export (base/export.py, base/package.py): the package of library A with what it must and must
not hold, as a zip (stored, zip64 when big) and as a folder, its checksums, its vectors under the keys a base of the
same cards gives, and the refusals (errors in the library, a taken name, a FAT32 disk)."""

import json, os, zipfile

import pytest

from assistant_x.base import export as X, package as P
from assistant_x.core import card as C
from assistant_x.core import config as settings
from assistant_x.core.common import connect, load_config
from tests.search.conftest import build, make_library
from tests.search.fake_embedder import embed


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    """Library A built and embedded with the fake model; N-00001 names X-00001 (personal) as another version."""
    root = str(tmp_path_factory.mktemp("export") / "A")
    path = make_library(root)
    p = os.path.join(root, "index", "cards", "N-00001.json")
    card = C.load(p)
    card["doc"]["other_versions"] = ["X-00001"]
    C.dump(card, p)
    with open(os.path.join(root, "index", "intake_events.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "date\tsource_file\tsize\tsha256\tcode\tdestination\tstatus\n"
            "2026-10-23\tinbox\\private folder\\gost.pdf\t10\tabc\tN-00001\tlibrary\\01_Standards\\x.pdf\tdone\n"
            "2026-10-23\tinbox\\trap.pdf\t10\tabd\tX-00001\tlibrary\\06_Other\\y.pdf\tdone\n"
        )
    build(path)
    embed(path)
    return path


def export(path, out, **kw):
    cfg = load_config(path)
    raw = settings.load(path)[1]
    return X.export(cfg, raw, str(out), kw.pop("ident", "test-a"), kw.pop("version", "1.0"), say=lambda s: None, **kw)


def test_the_package_of_a_library(library, tmp_path):
    out = tmp_path / "a.axbase"
    man = export(library, out, name={"en": "Test A", "ru": None})
    with P.Package(out) as pkg:
        names = set(pkg.names())
        assert pkg.verify() == []
        assert pkg.manifest == man
        assert {
            P.MANIFEST,
            P.CHECKSUMS,
            P.README,
            "events.tsv",
            "ocr_quality.tsv",
            "vectors/meta.json",
            "vectors/keys.bin",
            "vectors/vectors.f16",
        } <= names
        assert "cards/X-00001.json" not in names and not any("X-00001" in n for n in names)  # personal: left out
        assert {
            "cards/E-00001.json",
            "texts/E-00001-02.md",
            "library/04_Datasheets/E-00001_Test-Pump/E-00001-02_Trials.pdf",
        } <= names
        assert not any(n.endswith(".toml") or n.startswith((".assistant_x", "search/")) for n in names)
        card = json.loads(pkg.read("cards/N-00001.json"))
        assert card["intake"]["package"] == {"id": "test-a", "version": "1.0", "code": "N-00001"}
        assert card["intake"]["batch"] == "" and card["file"]["source_name"] == "N-00001.pdf"
        assert card["doc"]["other_versions"] == []  # X-00001 is not in the package
        assert C.validate(card, ("en", "ru")) == []
        events = pkg.read("events.tsv").decode("utf-8")
        assert "private folder" not in events and "X-00001" not in events and "\tN-00001\t" in events
        assert "L-00001" in pkg.read("ocr_quality.tsv").decode("utf-8")
        readme = pkg.read(P.README).decode("utf-8")
        assert "How to install (English)" in readme and "Как" in readme  # the Russian part from lang/ru
        assert not any("LICENSE" in n.upper() for n in names)  # a package says nothing of who made it
        assert "author" not in pkg.manifest and "content_license" not in pkg.manifest
        assert all(i.compress_type == zipfile.ZIP_STORED for i in pkg.zip.infolist())
    assert man["codes"] == "default"
    assert man["format"] == P.FORMAT and man["documents"] == 5 and man["shelves"] == {"E": 1, "J": 1, "L": 1, "N": 2}
    assert man["card_languages"] == ["en", "ru"] and man["profile"] == "oil-gas-ru" and "base_schema" not in man["requires"]
    assert man["requires"]["card_schema"] == 1 and man["embed"]["rows"] > 0 and man["name"] == {"en": "Test A"}
    doc = next(d for d in man["docs"] if d["code"] == "E-00001")
    assert doc["parts"] == ["E-00001-02"] and len(doc["text_sha"]) == 64


def test_the_vectors_of_a_package_are_under_the_keys_of_its_fragments(library, tmp_path):
    from assistant_x.search import embed as E, vector_cache as V

    out = tmp_path / "a.axbase"
    export(library, out)
    cfg = load_config(library)
    con = connect(cfg["db"], readonly=True)
    want = set(E.keys_of(E.fragments(con, "1"), V.fingerprint(cfg), False))
    personal = set(E.keys_of(E.fragments(con, "c.code = 'X-00001'"), V.fingerprint(cfg), False))
    con.close()
    with P.Package(out) as pkg:
        keys = pkg.read("vectors/keys.bin")
        info = json.loads(pkg.read("vectors/meta.json"))
        got = {keys[i : i + V.KEY_BYTES] for i in range(0, len(keys), V.KEY_BYTES)}
        assert len(pkg.read("vectors/vectors.f16")) == info["rows"] * info["dim"] * 2 == len(got) * info["dim"] * 2
    assert got == want - personal and info["fingerprint"] == V.fingerprint(cfg)


def test_include_personal_and_strip_names(library, tmp_path):
    out = tmp_path / "all.axbase"
    man = export(library, out, include_personal=True, strip_names=True, vectors=False)
    with P.Package(out) as pkg:
        assert "cards/X-00001.json" in pkg.names() and not any(n.startswith("vectors/") for n in pkg.names())
        card = json.loads(pkg.read("cards/E-00001.json"))
        assert card["file"]["source_name"] == "" and card["file"]["parts"][0]["source_name"] == ""
        assert json.loads(pkg.read("cards/N-00001.json"))["doc"]["other_versions"] == ["X-00001"]
    assert man["documents"] == 6 and man["embed"] is None


def test_a_folder_package(library, tmp_path):
    out = tmp_path / "folder"
    export(library, out, folder=True)
    with P.Package(out) as pkg:
        assert pkg.folder and pkg.verify() == [] and pkg.manifest["documents"] == 5
    with pytest.raises(SystemExit, match="must be empty"):
        export(library, out, folder=True)


def test_zip64(library, tmp_path, monkeypatch):
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1000)  # every file over 1000 bytes needs the zip64 records
    out = tmp_path / "big.axbase"
    export(library, out)
    with P.Package(out) as pkg:
        assert pkg.verify() == [] and pkg.manifest["documents"] == 5


def test_refusals(library, tmp_path, monkeypatch):
    out = tmp_path / "a.axbase"
    export(library, out)
    with pytest.raises(SystemExit, match="exists already"):
        export(library, out)
    with pytest.raises(SystemExit, match="--codes"):
        export(library, tmp_path / "d.axbase", codes="mine")
    with pytest.raises(SystemExit, match="--id"):
        export(library, tmp_path / "b.axbase", ident="Bad Id")
    monkeypatch.setattr(X, "fs_type", lambda path: "FAT32")
    monkeypatch.setattr(X, "FAT32_LIMIT", 10)
    with pytest.raises(SystemExit, match="--folder"):
        export(library, tmp_path / "c.axbase")


def test_errors_in_the_library_stop_the_export(tmp_path):
    root = str(tmp_path / "A")
    path = make_library(root)
    os.remove(os.path.join(root, "index", "texts", "N-00002.md"))
    with pytest.raises(SystemExit, match="errors"):
        export(path, tmp_path / "a.axbase")
    assert not (tmp_path / "a.axbase").exists()


def test_a_damaged_package_is_found(library, tmp_path):
    out = tmp_path / "folder"
    export(library, out, folder=True)
    with open(out / "texts" / "N-00001.md", "a", encoding="utf-8") as f:
        f.write("tampered")
    os.remove(out / "texts" / "N-00002.md")
    with P.Package(out) as pkg:
        assert sorted(pkg.verify()) == ["damaged: texts/N-00001.md", "missing: texts/N-00002.md"]
    with pytest.raises(P.PackageError):
        P.Package(tmp_path / "none.axbase")


def test_the_command(library, tmp_path, capsys):
    from assistant_x.cli import main as cli

    out = tmp_path / "cmd"
    assert (
        cli.main(
            ["base", "export", str(out), "--id", "cmd-a", "--version", "2", "--config", library, "--name-en", "Command A"]
        )
        == 0
    )
    assert "Package cmd-a 2: 5 documents" in capsys.readouterr().out
    with P.Package(str(out) + P.SUFFIX) as pkg:
        assert pkg.manifest["name"] == {"en": "Command A"}
    assert cli.main(["base"]) == 0 and "base export" in capsys.readouterr().out
