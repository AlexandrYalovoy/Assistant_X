# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tools/unpack.py: safe unpacking beside the archive, refusals before anything is written, limits."""

import io, os, tarfile, zipfile

import pytest

from assistant_x.intake.tools import unpack


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def files_under(d):
    return sorted(os.path.relpath(os.path.join(dp, f), d).replace("\\", "/") for dp, _, fns in os.walk(d) for f in fns)


def test_zip_beside_archive(tmp_path):
    a = make_zip(tmp_path / "Документы.zip", {"a/x.pdf": b"%PDF-1", "y.txt": b"y"})
    rep = unpack.unpack(a)
    assert rep["error"] is None and rep["files"] == 2
    assert rep["dest"] == str(tmp_path / "Документы")
    assert files_under(tmp_path / "Документы") == ["a/x.pdf", "y.txt"]
    rep2 = unpack.unpack(a)  # the folder is taken: Документы_2
    assert rep2["dest"] == str(tmp_path / "Документы_2")


@pytest.mark.parametrize("name", ["../evil.txt", "a/../../evil.txt", "/etc/evil.txt", "C:/evil.txt", "C:\\evil.txt"])
def test_refuse_unsafe_names(tmp_path, name):
    a = make_zip(tmp_path / "bad.zip", {"ok.txt": b"ok", name: b"x"})
    rep = unpack.unpack(a)
    assert rep["error"] and ("absolute" in rep["error"] or ".." in rep["error"])
    assert not (tmp_path / "bad").exists()  # nothing written, not even the good file
    assert not (tmp_path.parent / "evil.txt").exists()


def test_refuse_unsafe_tar(tmp_path):
    a = tmp_path / "bad.tar"
    with tarfile.open(a, "w") as t:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    rep = unpack.unpack(a)
    assert rep["error"] and ".." in rep["error"] and not (tmp_path / "bad").exists()


def test_size_limit(tmp_path):
    a = make_zip(tmp_path / "big.zip", {"zeros.bin": b"\0" * 200_000})
    rep = unpack.unpack(a, max_total=100_000)
    assert rep["error"] and "limit" in rep["error"] and not (tmp_path / "big").exists()


def test_nested_depth_limit(tmp_path):
    inner = make_zip(tmp_path / "l3.zip", {"deep.pdf": b"%PDF-3"})
    data = inner.read_bytes()
    for k in (2, 1):  # l1.zip > l2.zip > l3.zip > deep.pdf
        p = tmp_path / f"l{k}.zip"
        make_zip(p, {f"l{k + 1}.zip": data})
        data = p.read_bytes()
    outer = make_zip(tmp_path / "outer.zip", {"l1.zip": data})
    rep = unpack.unpack(outer, max_depth=2)
    assert rep["error"] is None
    assert len(rep["nested"]) == 1 and rep["nested"][0].endswith("l1.zip")
    assert len(rep["left"]) == 1 and "nesting" in rep["left"][0]["why"]
    assert any(f.endswith("l2.zip") for f in files_under(rep["dest"]))  # left as an archive, not unpacked
    full = unpack.unpack(outer, max_depth=5)
    assert any(f.endswith("deep.pdf") for f in files_under(full["dest"])) and not full["left"]


def test_cp866_names(tmp_path):
    a = tmp_path / "ru.zip"
    with zipfile.ZipFile(a, "w") as z:
        z.writestr("XXXXX.txt", b"x")
    # how old archivers write Russian names: cp866 bytes, no UTF-8 flag (zipfile itself would write UTF-8)
    a.write_bytes(a.read_bytes().replace(b"XXXXX.txt", "Отчёт.txt".encode("cp866")))
    rep = unpack.unpack(a)
    assert files_under(rep["dest"]) == ["Отчёт.txt"]


def test_broken_archive(tmp_path):
    a = tmp_path / "broken.zip"
    a.write_bytes(b"PK\x03\x04 not really a zip")
    rep = unpack.unpack(a, sevenzip=None)
    assert rep["error"] and not (tmp_path / "broken").exists()


def test_a_refusal_says_its_kind():
    """The code reads Refused.kind, never the words of the message (they are for the user and may change)."""
    from assistant_x.intake.tools import unpack

    e = unpack.Refused("the archive is protected by a password", unpack.PASSWORD)
    assert e.kind == "password" and str(e) == "the archive is protected by a password"
    assert unpack.Refused("anything").kind == "damaged"


@pytest.mark.parametrize("name", ["CON.txt", "folder/nul", "com1.pdf"])
def test_device_names_of_windows_are_refused(tmp_path, name):
    """A device name of Windows in an archive (txn.bad_path): nothing is unpacked."""
    from assistant_x.intake.tools import unpack

    with pytest.raises(unpack.Refused) as e:
        unpack.safe_name(name)
    assert e.value.kind == "unsafe"


def test_signs_windows_refuses_in_a_name_become_underscores(tmp_path):
    """Trial batch b074: an archive was refused whole for a letter saved under its subject ('RE: FW: ... "Name"
    <mail>'). The signs Windows refuses become "_" (a colon makes no NTFS stream), a part loses its ending dots and
    spaces; a path that climbs out or is absolute stays refused."""
    from assistant_x.intake.tools import unpack

    assert unpack.safe_name('Письма/RE: FW: АВО - "Ivanov, I" <i@x.com> 2024.eml') == [
        "Письма",
        "RE_ FW_ АВО - _Ivanov, I_ _i@x.com_ 2024.eml",
    ]
    assert unpack.safe_name("a.pdf:hidden") == ["a.pdf_hidden"]
    assert unpack.safe_name("doc.pdf.") == ["doc.pdf"] and unpack.safe_name("folder /x.pdf") == ["folder", "x.pdf"]
    a = make_zip(tmp_path / "mail.zip", {'RE: FW: "x".eml': b"letter", "ok.txt": b"ok"})
    rep = unpack.unpack(a)
    assert rep["error"] is None and files_under(rep["dest"]) == ["RE_ FW_ _x_.eml", "ok.txt"]
    assert unpack.safe_name(r"Папка\.\sub/doc.pdf") == ["Папка", "sub", "doc.pdf"]
    assert unpack.safe_name("e\u0301.pdf") == ["\u00e9.pdf"]  # a macOS name: made NFC, not refused


def test_an_archive_split_in_volumes_is_unpacked_from_its_first_one(tmp_path):
    """Trial batch b007: "X.7z.001" was left as a file the intake does not process. The first volume is an archive,
    the next ones go with it."""
    from assistant_x.core.formats import file_kind
    from assistant_x.intake import config as intake_cfg

    data = make_zip(tmp_path / "whole.zip", {"doc.txt": b"x" * 5000, "b/two.txt": b"y" * 5000}).read_bytes()
    half = len(data) // 2
    (tmp_path / "X.zip.001").write_bytes(data[:half])
    (tmp_path / "X.zip.002").write_bytes(data[half:])
    assert file_kind("X.7z.001") == file_kind("X.001") == "archive" and file_kind("X.7z.002") != "archive"
    assert unpack.volumes(tmp_path / "X.zip.001") == [tmp_path / "X.zip.002"]
    assert unpack.volumes(tmp_path / "whole.zip") == [] and unpack.volumes(tmp_path / "X.zip.002") == []
    assert unpack.target_dir(tmp_path / "X.zip.001") == tmp_path / "X"
    sevenzip = intake_cfg.find_sevenzip()
    if not sevenzip:
        pytest.skip("no 7-Zip on this PC")
    rep = unpack.unpack(tmp_path / "X.zip.001", sevenzip=str(sevenzip))
    assert rep["error"] is None and files_under(rep["dest"]) == ["b/two.txt", "doc.txt"]


def test_an_archive_of_too_many_files_is_refused(tmp_path):
    """Audit 9 S-02: 20 000 empty members (a zip of 2 MB) gave 20 000 files of the batch; the count is limited now
    ([intake.unpack] max_files), for the archive and its nested ones together, and nothing is left behind."""
    import io, zipfile

    many = tmp_path / "many.zip"
    with zipfile.ZipFile(many, "w") as z:
        for i in range(30):
            z.writestr(f"d/{i}.txt", b"")
    rep = unpack.unpack(many, max_files=20)
    assert rep["error"] and rep["kind"] == "size" and "30 files" in rep["error"] and not (tmp_path / "many").exists()
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        for i in range(15):
            z.writestr(f"{i}.txt", b"")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as z:
        for i in range(10):
            z.writestr(f"{i}.txt", b"")
        z.writestr("inner.zip", inner.getvalue())
    rep = unpack.unpack(outer, max_files=20)
    assert not rep["error"] and rep["left"] and rep["left"][0]["kind"] == "size"  # the nested one is left whole
    assert unpack.LIMITS["max_files"] >= 10000


def test_two_members_whose_names_differ_in_case_are_both_kept(tmp_path):
    """Audit 9 S-03: Report.pdf and REPORT.PDF in one zip: Windows keeps one file of the two, the first was lost."""
    import zipfile

    z = tmp_path / "c.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Report.pdf", b"first")
        f.writestr("REPORT.PDF", b"second")
    rep = unpack.unpack(z)
    got = sorted(p.read_bytes() for p in (tmp_path / "c").iterdir())
    assert not rep["error"] and got == [b"first", b"second"]
