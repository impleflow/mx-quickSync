# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Tests of the path values in the configuration: relative paths are resolved against the defining file."""

from pathlib import Path

import loadConfig
import pytest


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake repo root (with .git) as the working directory."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestPaths:
    def test_relative_path_is_resolved_against_the_defining_file(self, repo, monkeypatch):
        write(repo / "cfg" / "config.yaml", "maximo_smp_dir: ../java/maximo_SMP\n")
        monkeypatch.chdir(repo / "cfg")
        cfg = loadConfig.load_config(repo / "cfg", quiet=True)
        assert cfg.path("maximo_smp_dir") == (repo / "java" / "maximo_SMP").resolve()

    def test_result_does_not_depend_on_the_working_directory(self, repo, monkeypatch):
        write(repo / "config.yaml", "maximo_smp_dir: maximo_SMP\n")
        monkeypatch.chdir(repo)
        cfg = loadConfig.load_config(repo, quiet=True)
        first = cfg.path("maximo_smp_dir")
        monkeypatch.chdir(repo.parent)
        assert cfg.path("maximo_smp_dir") == first == (repo / "maximo_SMP").resolve()

    def test_absolute_path_is_returned_unchanged(self, repo):
        absolute = (repo / "elsewhere").resolve()
        write(repo / "config.yaml", f"maximo_smp_dir: '{absolute}'\n")
        assert loadConfig.load_config(repo, quiet=True).path("maximo_smp_dir") == absolute

    def test_value_from_a_later_layer_is_relative_to_that_layer(self, repo):
        write(repo / "config.yaml", "maximo_smp_dir: from_config\n")
        write(repo / "local.yaml", "maximo_smp_dir: from_local\n")
        cfg = loadConfig.load_config(repo, quiet=True)
        assert cfg.path("maximo_smp_dir") == (repo / "from_local").resolve()

    def test_each_value_uses_its_own_file(self, repo, monkeypatch):
        write(repo / "config.yaml", "section:\n  a: dir_a\n")
        write(repo / "sub" / "local.yaml", "section:\n  b: dir_b\n")
        monkeypatch.chdir(repo / "sub")
        cfg = loadConfig.load_config(repo / "sub", quiet=True)
        assert cfg.path("section", "a") == (repo / "dir_a").resolve()
        assert cfg.path("section", "b") == (repo / "sub" / "dir_b").resolve()

    def test_missing_path_is_none(self, repo):
        write(repo / "config.yaml", "a: 1\n")
        assert loadConfig.load_config(repo, quiet=True).path("maximo_smp_dir") is None

    def test_required_path_exits_naming_the_key(self, repo):
        write(repo / "config.yaml", "a: 1\n")
        cfg = loadConfig.load_config(repo, quiet=True)
        with pytest.raises(SystemExit) as exc:
            cfg.path("maximo_smp_dir", required=True)
        assert "maximo_smp_dir" in str(exc.value)

    def test_without_origin_information_the_first_file_directory_is_used(self, tmp_path):
        cfg = loadConfig.Config({"maximo_smp_dir": "x"}, [tmp_path / "config.yaml"])
        assert cfg.path("maximo_smp_dir") == (tmp_path / "x").resolve()

    def test_origin_is_the_directory_of_the_defining_file(self, repo, monkeypatch):
        write(repo / "config.yaml", "section:\n  a: 1\n")
        write(repo / "sub" / "local.yaml", "section:\n  b: 2\n")
        monkeypatch.chdir(repo / "sub")
        cfg = loadConfig.load_config(repo / "sub", quiet=True)
        assert cfg.origin("section", "a") == repo
        assert cfg.origin("section", "b") == repo / "sub"
        assert cfg.origin("not", "there") == cfg.files[0].parent


class TestLeafKeys:
    def test_lists_and_empty_dicts_are_leaves(self):
        data = {"a": {"b": 1, "c": [1, 2]}, "d": {}}
        assert sorted(loadConfig.leaf_keys(data)) == [("a", "b"), ("a", "c"), ("d",)]

    def test_lookup(self):
        assert loadConfig.lookup({"a": {"b": 5}}, ("a", "b")) == 5
        assert loadConfig.lookup({"a": {"b": 5}}, ("a", "x")) is None
        assert loadConfig.lookup({"a": 1}, ("a", "b")) is None
