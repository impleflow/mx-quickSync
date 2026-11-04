#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Layered tool configuration from YAML files (config.yaml, secrets.yaml, local.yaml).

Requires PyYAML.

Where the files are read from:
- searched in the script directory and in the directory the script was started from, and in all their parent
  directories - up to and including the directory containing .git; without .git only the starting directory is used,
- within each layer the closer directory wins over the farther one.

Layers (lowest first; each next one overrides the previous one):
1. config.yaml  - shared configuration, in the repo,
2. secrets.yaml - team-wide credentials, in the repo, encrypted with sops (optional),
3. local.yaml   - personal data and local overrides, in .gitignore (optional).

Merging: dictionaries recursively, everything else (including lists) is replaced as a whole.
Path values (see Config.path): absolute paths are used as they are, relative ones are resolved
against the directory of the file that defined the value (not against the directory the script was started from).
A file with a `sops:` block is decrypted with the `sops -d` command (requires sops to be installed).

Structure:
    maximo_smp_dir: <path>   # root of the MAS sources (absolute or relative to this file)
    environments:
      <env>:          # facts about the environment (server, oc_auth, nodes, ...)
    tools:
      <tool>:         # settings of a single tool; tools.<tool>.environments.<env> overrides them per environment
"""

import subprocess
import sys
from pathlib import Path

import logUtils
import yaml

LAYERS = ("config.yaml", "secrets.yaml", "local.yaml")


def _chain(start: Path) -> list:
    """Starting directory and its parents - up to the directory with .git (no .git: only the starting directory).
    Closest first."""
    chain = []
    for directory in [start, *start.parents]:
        chain.append(directory)
        if (directory / ".git").exists():
            return chain
    return [start]


def search_dirs(script_dir: Path) -> list:
    """Directories to search, from the lowest to the highest priority (run directory > script directory)."""
    ordered = []
    for start in (script_dir, Path.cwd()):
        for directory in reversed(_chain(start.resolve())):
            if directory in ordered:
                ordered.remove(directory)
            ordered.append(directory)
    return ordered


def leaf_keys(data: dict, prefix: tuple = ()):
    """Key paths of all leaves of a nested dictionary (lists and empty dictionaries are leaves)."""
    for key, value in data.items():
        if isinstance(value, dict) and value:
            yield from leaf_keys(value, prefix + (key,))
        else:
            yield prefix + (key,)


def lookup(data: dict, keys: tuple):
    """Value at the key path, or None if any key on the way is missing."""
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        sys.exit(f"{path}: expected a YAML dictionary at the top level.")
    if "sops" in data:
        try:
            res = subprocess.run(["sops", "-d", str(path)], capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError:
            sys.exit(f"{path} is encrypted with sops, but the `sops` command is not available in PATH.")
        if res.returncode != 0:
            sys.exit(f"sops -d {path} failed:\n{res.stderr.strip()}")
        data = yaml.safe_load(res.stdout) or {}
    return data


class Config:
    def __init__(self, data: dict, files: list, origins: dict = None):
        self.data = data
        self.files = files
        # key path -> directory of the file that defined the value (the last layer wins)
        self.origins = origins or {}

    def environment_names(self) -> list:
        return sorted((self.data.get("environments") or {}).keys())

    def environment(self, env: str) -> dict:
        environments = self.data.get("environments") or {}
        if env not in environments:
            sys.exit(f"Unknown environment '{env}'. Available: {', '.join(self.environment_names()) or '(none)'}")
        return environments[env] or {}

    def tool(self, name: str, env: str = None) -> dict:
        """Tool settings; with `env` merged with tools.<name>.environments.<env>."""
        section = dict((self.data.get("tools") or {}).get(name) or {})
        per_env = section.pop("environments", None) or {}
        return deep_merge(section, per_env.get(env) or {}) if env else section

    def path(self, *keys: str, required: bool = False):
        """Path stored under the key path (e.g. path("maximo_smp_dir")) or None if it is not set.

        An absolute path is returned as it is, a relative one is resolved against the directory of the file that
        defined the value. required=True exits with a message naming the key instead of returning None.
        """
        value = lookup(self.data, keys)
        if value in (None, ""):
            if required:
                sys.exit(f"Missing {'.'.join(keys)} in the configuration (config.yaml / secrets.yaml / local.yaml).")
            return None
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            return path
        return (self.origin(*keys) / path).resolve()

    def origin(self, *keys: str) -> Path:
        """Directory of the file that defined the key path (relative values are relative to it).

        Falls back to the directory of the first file read (or the current directory) when the origin is not known.
        """
        return self.origins.get(tuple(keys)) or (self.files[0].parent if self.files else Path.cwd())


def require(section: dict, key: str, where: str):
    """Returns section[key] or exits with a message pointing at the missing key (e.g. environments.demo.server)."""
    value = section.get(key)
    if value in (None, "", {}, []):
        sys.exit(f"Missing {where}.{key} in the configuration (config.yaml / secrets.yaml / local.yaml).")
    return value


def load_config(script_dir: Path, quiet: bool = False) -> Config:
    dirs = search_dirs(Path(script_dir))
    data, files, origins = {}, [], {}
    for layer in LAYERS:
        for directory in dirs:
            path = directory / layer
            if path.is_file():
                file_data = read_yaml(path)
                data = deep_merge(data, file_data)
                origins.update({key: path.parent for key in leaf_keys(file_data)})
                files.append(path)
    if not files:
        sys.exit("config.yaml not found in: " + ", ".join(str(d) for d in dirs))
    if not quiet:
        logUtils.log("config: " + ", ".join(str(f) for f in files), sys.stderr)
    return Config(data, files, origins)
