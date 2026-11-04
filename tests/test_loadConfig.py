# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Tests of the layered YAML configuration loader (loadConfig.py)."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

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


class TestDeepMerge:
    def test_nested_dicts_are_merged(self):
        base = {"a": {"x": 1, "y": 2}, "b": 1}
        override = {"a": {"y": 20, "z": 30}}
        assert loadConfig.deep_merge(base, override) == {"a": {"x": 1, "y": 20, "z": 30}, "b": 1}

    def test_lists_are_replaced_not_merged(self):
        assert loadConfig.deep_merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}

    def test_scalar_replaces_dict(self):
        assert loadConfig.deep_merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}

    def test_inputs_are_not_mutated(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        loadConfig.deep_merge(base, override)
        assert base == {"a": {"x": 1}}
        assert override == {"a": {"y": 2}}


class TestRequire:
    def test_returns_value(self):
        assert loadConfig.require({"server": "https://x"}, "server", "environments.demo") == "https://x"

    @pytest.mark.parametrize("empty", [None, "", {}, []])
    def test_exits_on_empty_value(self, empty):
        with pytest.raises(SystemExit) as exc:
            loadConfig.require({"server": empty}, "server", "environments.demo")
        assert "environments.demo.server" in str(exc.value)

    def test_exits_on_missing_key(self):
        with pytest.raises(SystemExit) as exc:
            loadConfig.require({}, "server", "environments.demo")
        assert "environments.demo.server" in str(exc.value)

    def test_zero_and_false_are_valid_values(self):
        assert loadConfig.require({"n": 0}, "n", "w") == 0
        assert loadConfig.require({"flag": False}, "flag", "w") is False


class TestLoadConfig:
    def test_missing_config_exits(self, repo):
        with pytest.raises(SystemExit) as exc:
            loadConfig.load_config(repo, quiet=True)
        assert "config.yaml not found" in str(exc.value)

    def test_reads_config_yaml(self, repo):
        write(repo / "config.yaml", "environments:\n  demo:\n    server: https://demo\n")
        cfg = loadConfig.load_config(repo, quiet=True)
        assert cfg.environment("demo")["server"] == "https://demo"
        assert cfg.files == [repo / "config.yaml"]

    def test_layers_override_in_order(self, repo):
        write(repo / "config.yaml", "environments:\n  demo:\n    server: base\n    ns: base-ns\n")
        write(repo / "secrets.yaml", "environments:\n  demo:\n    server: secret\n")
        write(repo / "local.yaml", "environments:\n  demo:\n    ns: local-ns\n")
        env = loadConfig.load_config(repo, quiet=True).environment("demo")
        assert env == {"server": "secret", "ns": "local-ns"}

    def test_closer_directory_wins_within_a_layer(self, repo, monkeypatch):
        write(repo / "config.yaml", "value: root\nroot_only: 1\n")
        write(repo / "tools" / "config.yaml", "value: tools\n")
        monkeypatch.chdir(repo / "tools")
        data = loadConfig.load_config(repo / "tools", quiet=True).data
        assert data == {"value": "tools", "root_only": 1}

    def test_search_stops_at_git_directory(self, tmp_path, monkeypatch):
        outer = tmp_path
        repo = outer / "repo"
        (repo / ".git").mkdir(parents=True)
        write(outer / "config.yaml", "leaked: true\n")
        write(repo / "config.yaml", "ok: true\n")
        monkeypatch.chdir(repo)
        assert loadConfig.load_config(repo, quiet=True).data == {"ok": True}

    def test_without_git_only_start_directory_is_used(self, tmp_path, monkeypatch):
        write(tmp_path / "config.yaml", "parent: true\n")
        child = tmp_path / "child"
        write(child / "config.yaml", "child: true\n")
        monkeypatch.chdir(child)
        assert loadConfig.load_config(child, quiet=True).data == {"child": True}

    def test_working_directory_wins_over_script_directory(self, repo, monkeypatch):
        script_dir = repo / "scripts"
        project_dir = repo / "project"
        write(script_dir / "config.yaml", "value: script\n")
        write(project_dir / "config.yaml", "value: project\n")
        monkeypatch.chdir(project_dir)
        assert loadConfig.load_config(script_dir, quiet=True).data["value"] == "project"

    def test_loaded_files_are_reported_on_stderr(self, repo, capsys):
        write(repo / "config.yaml", "a: 1\n")
        loadConfig.load_config(repo)
        assert "config.yaml" in capsys.readouterr().err

    def test_empty_file_is_treated_as_empty_dict(self, repo):
        write(repo / "config.yaml", "")
        assert loadConfig.load_config(repo, quiet=True).data == {}


class TestReadYaml:
    def test_non_dict_top_level_exits(self, tmp_path):
        path = write(tmp_path / "bad.yaml", "- a\n- b\n")
        with pytest.raises(SystemExit) as exc:
            loadConfig.read_yaml(path)
        assert "YAML dictionary" in str(exc.value)

    def test_sops_file_is_decrypted(self, tmp_path, monkeypatch):
        path = write(tmp_path / "secrets.yaml", "sops:\n  version: 3\nenvironments: {}\n")

        def fake_run(cmd, **kwargs):
            assert cmd == ["sops", "-d", str(path)]
            return SimpleNamespace(returncode=0, stdout="environments:\n  demo:\n    oc_auth: secret\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert loadConfig.read_yaml(path) == {"environments": {"demo": {"oc_auth": "secret"}}}

    def test_sops_not_installed_exits(self, tmp_path, monkeypatch):
        path = write(tmp_path / "secrets.yaml", "sops:\n  version: 3\n")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as exc:
            loadConfig.read_yaml(path)
        assert "sops" in str(exc.value)

    def test_sops_failure_exits_with_stderr(self, tmp_path, monkeypatch):
        path = write(tmp_path / "secrets.yaml", "sops:\n  version: 3\n")
        monkeypatch.setattr(
            subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="no key")
        )
        with pytest.raises(SystemExit) as exc:
            loadConfig.read_yaml(path)
        assert "no key" in str(exc.value)


class TestConfig:
    DATA = {
        "environments": {"b-env": {"server": "b"}, "a-env": {"server": "a"}},
        "tools": {
            "tool1": {
                "keep": 3,
                "mode": "x",
                "environments": {"a-env": {"keep": 5}},
            }
        },
    }

    def test_environment_names_are_sorted(self):
        assert loadConfig.Config(self.DATA, []).environment_names() == ["a-env", "b-env"]

    def test_unknown_environment_exits_and_lists_available(self):
        with pytest.raises(SystemExit) as exc:
            loadConfig.Config(self.DATA, []).environment("zzz")
        assert "a-env, b-env" in str(exc.value)

    def test_tool_without_env_returns_section_without_overrides(self):
        tool = loadConfig.Config(self.DATA, []).tool("tool1")
        assert tool == {"keep": 3, "mode": "x"}

    def test_tool_with_env_applies_override(self):
        cfg = loadConfig.Config(self.DATA, [])
        assert cfg.tool("tool1", "a-env") == {"keep": 5, "mode": "x"}
        assert cfg.tool("tool1", "b-env") == {"keep": 3, "mode": "x"}

    def test_unknown_tool_is_empty(self):
        assert loadConfig.Config(self.DATA, []).tool("nope", "a-env") == {}

    def test_tool_does_not_mutate_config_data(self):
        cfg = loadConfig.Config(self.DATA, [])
        cfg.tool("tool1", "a-env")
        assert "environments" in cfg.data["tools"]["tool1"]
