# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""The example configuration files must stay valid and must not contain internal data."""

from pathlib import Path

import loadConfig
import pytest
import yaml

import quickSync

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ("config.yaml.example", "local.yaml.example")


def load_example() -> loadConfig.Config:
    """config.yaml.example overridden by local.yaml.example, as the loader would merge config.yaml and local.yaml."""
    config_path = ROOT / "config.yaml.example"
    data = {}
    for name in EXAMPLES:
        data = loadConfig.deep_merge(data, yaml.safe_load((ROOT / name).read_text(encoding="utf-8")))
    return loadConfig.Config(data, [config_path])


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_is_a_yaml_dictionary(name):
    assert isinstance(yaml.safe_load((ROOT / name).read_text(encoding="utf-8")), dict)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_contains_no_internal_names(name):
    text = (ROOT / name).read_text(encoding="utf-8").lower()
    assert "impleflow" not in text


def test_local_example_has_only_placeholders_for_credentials():
    local = yaml.safe_load((ROOT / "local.yaml.example").read_text(encoding="utf-8"))
    assert local["environments"]["dev"]["oc_auth"] == "--token=<token>"


def test_environment_has_everything_quicksync_requires():
    env = load_example().environment("dev")
    assert env["quick_sync"] is True
    for key in ("server", "manage_namespace", "oc_auth"):
        assert env[key]
    assert env["nodes"][quickSync.NODE_NAME]["pod"]


def test_maximo_smp_dir_is_resolved_relative_to_the_example_file():
    assert load_example().path("maximo_smp_dir", required=True) == (ROOT / "../maximo_SMP").resolve()


def test_class_directories_are_accepted_by_quicksync():
    classes = quickSync.classes_dirs(load_example().tool("quickSync", "dev"))
    assert set(classes) == {module.config_key for module in quickSync.NESTED_MODULES}
