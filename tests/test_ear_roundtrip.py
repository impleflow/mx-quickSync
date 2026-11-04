# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Tests of the scripts that run on the pod (unZipEar.py, zipEar.py) using a small fake EAR in a temp directory."""

import re
import sys
import zipfile
from pathlib import Path

import pytest
import quickSyncCfg
import unZipEar
import zipEar

MANIFEST = "META-INF/MANIFEST.MF"


def make_zip(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def pod(tmp_path, monkeypatch):
    """Redirects the pod paths (/tmp/...) to a temp directory and builds a fake EAR."""
    unpack = tmp_path / "maximo.unpack"
    ear_out = tmp_path / "maximo.ear"
    modules = [
        quickSyncCfg.NestedModule("businessobjects.jar", str(tmp_path / "bo.unpack"), ""),
        quickSyncCfg.NestedModule("maximouiweb.war", str(tmp_path / "ui.unpack"), "WEB-INF/classes"),
    ]
    for module in (unZipEar, zipEar):
        monkeypatch.setattr(module, "MAXIMO_UNPACK_DIR", str(unpack))
        monkeypatch.setattr(module, "NESTED_MODULES", modules)
    monkeypatch.setattr(zipEar, "MAXIMO_EAR_FILE", str(ear_out))

    bo_jar = make_zip(tmp_path / "bo.jar", {MANIFEST: "Manifest-Version: 1.0\n", "pkg/A.class": "old-A"})
    ui_war = make_zip(tmp_path / "ui.war", {"WEB-INF/web.xml": "<web/>", "index.html": "hi"})
    ear = make_zip(
        tmp_path / "in.ear",
        {
            MANIFEST: "Manifest-Version: 1.0\n",
            "businessobjects.jar": bo_jar.read_bytes(),
            "maximouiweb.war": ui_war.read_bytes(),
            "readme.txt": "text",
        },
    )
    return SimpleNamespace(unpack=unpack, ear_out=ear_out, ear=ear, modules=modules, tmp=tmp_path)


class SimpleNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def run_unzip(ear: Path) -> None:
    sys.argv = ["unZipEar.py", str(ear)]
    unZipEar.main()


class TestUnZipEar:
    def test_unpacks_ear_and_nested_modules(self, pod):
        run_unzip(pod.ear)
        assert (pod.unpack / "readme.txt").read_text() == "text"
        assert (Path(pod.modules[0].unpack_dir) / "pkg" / "A.class").read_text() == "old-A"
        assert (Path(pod.modules[1].unpack_dir) / "WEB-INF" / "web.xml").read_text() == "<web/>"

    def test_partial_directory_is_renamed_at_the_end(self, pod):
        run_unzip(pod.ear)
        assert pod.unpack.is_dir()
        assert not Path(str(pod.unpack) + ".partial").exists()

    def test_is_skipped_when_already_unpacked(self, pod, capsys):
        pod.unpack.mkdir()
        (pod.unpack / "marker").write_text("keep")
        run_unzip(pod.ear)
        assert (pod.unpack / "marker").read_text() == "keep"
        assert "skipped" in capsys.readouterr().out

    def test_directory_instead_of_ear_exits(self, pod):
        with pytest.raises(SystemExit) as exc:
            run_unzip(pod.tmp)
        assert "not an EAR file" in str(exc.value)

    def test_missing_nested_module_exits(self, pod):
        ear = make_zip(pod.tmp / "bad.ear", {"readme.txt": "x"})
        with pytest.raises(SystemExit) as exc:
            run_unzip(ear)
        assert "businessobjects.jar not found" in str(exc.value)

    def test_wrong_number_of_arguments_exits(self, pod):
        sys.argv = ["unZipEar.py"]
        with pytest.raises(SystemExit) as exc:
            unZipEar.main()
        assert "Usage" in str(exc.value)

    def test_extract_replaces_existing_destination(self, tmp_path):
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "stale.txt").write_text("stale")
        unZipEar.extract(str(make_zip(tmp_path / "a.zip", {"new.txt": "n"})), str(dest), "a", "dest")
        assert not (dest / "stale.txt").exists()
        assert (dest / "new.txt").read_text() == "n"


class TestCollectEntries:
    def test_manifest_comes_first(self, tmp_path):
        (tmp_path / "META-INF").mkdir()
        (tmp_path / "META-INF" / "MANIFEST.MF").write_text("m")
        (tmp_path / "META-INF" / "other.txt").write_text("o")
        (tmp_path / "a.txt").write_text("a")
        names = [arc for _, arc in zipEar.collect_entries(str(tmp_path))]
        assert names[:2] == ["META-INF/", MANIFEST]
        assert set(names) == {"META-INF/", MANIFEST, "META-INF/other.txt", "a.txt"}

    def test_directories_have_trailing_slash_and_posix_separators(self, tmp_path):
        (tmp_path / "x" / "y").mkdir(parents=True)
        (tmp_path / "x" / "y" / "f.txt").write_text("f")
        names = [arc for _, arc in zipEar.collect_entries(str(tmp_path))]
        assert "x/" in names and "x/y/" in names and "x/y/f.txt" in names

    def test_order_is_deterministic(self, tmp_path):
        for name in ("b.txt", "a.txt", "c.txt"):
            (tmp_path / name).write_text(name)
        names = [arc for _, arc in zipEar.collect_entries(str(tmp_path))]
        assert names == ["a.txt", "b.txt", "c.txt"]


class TestPack:
    def test_compressed_files_are_stored_others_deflated(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "inner.jar").write_bytes(b"x" * 1000)
        (src / "data.txt").write_bytes(b"y" * 1000)
        dest = tmp_path / "out.zip"
        zipEar.pack(str(src), str(dest))
        with zipfile.ZipFile(dest) as zf:
            assert zf.getinfo("inner.jar").compress_type == zipfile.ZIP_STORED
            assert zf.getinfo("data.txt").compress_type == zipfile.ZIP_DEFLATED

    def test_no_tmp_file_left_after_success(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("f")
        dest = tmp_path / "out.zip"
        zipEar.pack(str(src), str(dest))
        assert dest.is_file()
        assert not Path(str(dest) + ".tmp").exists()

    def test_existing_destination_is_replaced(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("n")
        dest = make_zip(tmp_path / "out.zip", {"old.txt": "o"})
        zipEar.pack(str(src), str(dest))
        with zipfile.ZipFile(dest) as zf:
            assert zf.namelist() == ["new.txt"]


class TestZipEar:
    def test_missing_unpack_dir_exits(self, pod):
        with pytest.raises(SystemExit) as exc:
            zipEar.main()
        assert "unZipEar.py first" in str(exc.value)

    def test_missing_module_dir_exits(self, pod):
        pod.unpack.mkdir()
        with pytest.raises(SystemExit) as exc:
            zipEar.main()
        assert "unZipEar.py again" in str(exc.value)

    def test_roundtrip_applies_modified_class(self, pod):
        run_unzip(pod.ear)
        # simulate what remoteCp does: copy a new compiled class into the unpacked module
        (Path(pod.modules[0].unpack_dir) / "pkg" / "A.class").write_text("new-A")
        (Path(pod.modules[1].unpack_dir) / "WEB-INF" / "classes").mkdir()
        (Path(pod.modules[1].unpack_dir) / "WEB-INF" / "classes" / "B.class").write_text("B")

        zipEar.main()

        with zipfile.ZipFile(pod.ear_out) as ear:
            assert ear.namelist()[:2] == ["META-INF/", MANIFEST]
            assert {"businessobjects.jar", "maximouiweb.war", "readme.txt"} <= set(ear.namelist())
            nested_bo = pod.tmp / "bo_out.jar"
            nested_bo.write_bytes(ear.read("businessobjects.jar"))
            nested_ui = pod.tmp / "ui_out.war"
            nested_ui.write_bytes(ear.read("maximouiweb.war"))
        with zipfile.ZipFile(nested_bo) as bo:
            assert bo.read("pkg/A.class") == b"new-A"
            assert bo.namelist()[0] == MANIFEST or bo.namelist()[:2] == ["META-INF/", MANIFEST]
        with zipfile.ZipFile(nested_ui) as ui:
            assert ui.read("WEB-INF/classes/B.class") == b"B"
            assert ui.read("WEB-INF/web.xml") == b"<web/>"

    def test_nested_archives_are_stored_uncompressed_in_ear(self, pod):
        run_unzip(pod.ear)
        zipEar.main()
        with zipfile.ZipFile(pod.ear_out) as ear:
            assert ear.getinfo("businessobjects.jar").compress_type == zipfile.ZIP_STORED
            assert ear.getinfo("maximouiweb.war").compress_type == zipfile.ZIP_STORED


class TestPodConfig:
    def test_modules_have_unique_entries_and_dirs(self):
        entries = [m.ear_entry for m in quickSyncCfg.NESTED_MODULES]
        dirs = [m.unpack_dir for m in quickSyncCfg.NESTED_MODULES]
        assert len(set(entries)) == len(entries)
        assert len(set(dirs)) == len(dirs)

    def test_unpack_dirs_are_outside_the_ear_working_dir(self):
        # a nested module unpacked inside MAXIMO_UNPACK_DIR would end up in the repacked EAR twice
        for module in quickSyncCfg.NESTED_MODULES:
            assert not module.unpack_dir.startswith(quickSyncCfg.MAXIMO_UNPACK_DIR + "/")

    def test_log_prefixes_message_with_timestamp(self, capsys):
        quickSyncCfg.log("hello")
        out = capsys.readouterr().out
        assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d hello\n", out)
