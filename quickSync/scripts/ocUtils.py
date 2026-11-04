#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Running external commands, and `oc` against a temporary kubeconfig (the current `oc` context is never touched).

The `oc login` arguments (credentials) never appear in messages.
"""

import os
import shlex
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def run(
    *cmd: str, cwd=None, env=None, check: bool = True, capture: bool = True, timeout: float = None
) -> subprocess.CompletedProcess:
    """Runs cmd and returns the result; with check=True a non-zero exit code exits with the command output.

    capture=False lets the output go straight to the console (long commands that report their progress); the exit
    message then has no output. A missing executable always exits with a message instead of a traceback.
    stdin is always closed (DEVNULL), so a command that unexpectedly prompts for input fails fast instead of
    hanging silently; timeout (seconds, None = no limit) exits with a message instead of hanging forever on a
    stalled command (e.g. an unreachable server).
    """
    try:
        res = subprocess.run(
            list(cmd),
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except FileNotFoundError:
        sys.exit(f"`{cmd[0]}` not found in PATH.")
    except subprocess.TimeoutExpired:
        sys.exit(f"{' '.join(cmd)} timed out after {timeout} s.")
    if check and res.returncode != 0:
        output = ((res.stderr or res.stdout) or "").strip() if capture else ""
        sys.exit(f"{' '.join(cmd)} failed (exit code {res.returncode})" + (f":\n{output}" if output else "."))
    return res


def kubeconfig_env(kubeconfig: str) -> dict:
    """The environment of an `oc` process that uses the given kubeconfig."""
    return {**os.environ, "KUBECONFIG": kubeconfig}


def oc(
    kubeconfig: str, *args: str, cwd=None, check: bool = False, capture: bool = True, timeout: float = None
) -> subprocess.CompletedProcess:
    return run("oc", *args, cwd=cwd, env=kubeconfig_env(kubeconfig), check=check, capture=capture, timeout=timeout)


def oc_ok(kubeconfig: str, *args: str, cwd=None, timeout: float = None) -> str:
    """Output of a successful `oc` command; exits with its error output otherwise."""
    return oc(kubeconfig, *args, cwd=cwd, check=True, timeout=timeout).stdout


def require_login(oc_auth, env: str, skip_tls_verify: bool = True) -> str:
    """environments.<env>.oc_auth (the `oc login` arguments); exits with a hint where to put it when missing.

    skip_tls_verify (environments.<env>.oc_skip_tls_verify, default True) appends --insecure-skip-tls-verify,
    unless it is already present in oc_auth.
    """
    if not oc_auth:
        sys.exit(
            f"Missing environments.{env}.oc_auth - fill it in local.yaml or secrets.yaml "
            f"(template: local.yaml.example)."
        )
    args = str(oc_auth)
    if skip_tls_verify and "--insecure-skip-tls-verify" not in args:
        args += " --insecure-skip-tls-verify"
    return args


LOGIN_TIMEOUT = 60  # seconds; oc login should either succeed, fail or prompt (and then fail fast) well within this


def login(kubeconfig: str, server: str, login_args: str) -> None:
    """`oc login` into kubeconfig; login_args are split like a shell would split them."""
    res = oc(kubeconfig, "login", server, *shlex.split(login_args, posix=True), timeout=LOGIN_TIMEOUT)
    if res.returncode != 0:
        sys.exit(f"oc login {server} failed:\n{(res.stderr or res.stdout).strip()}")


@contextmanager
def oc_session(server: str, login_args: str):
    """Logs in to server into a temporary kubeconfig and yields its path; the file is removed at the end."""
    with tempfile.TemporaryDirectory(prefix="kubeconfig-") as tmp:
        kubeconfig = str(Path(tmp) / "kubeconfig")
        login(kubeconfig, server, login_args)
        yield kubeconfig


def pod_names(kubeconfig: str, namespace: str) -> list:
    """Names of the pods in namespace, the oldest first."""
    out = oc_ok(kubeconfig, "get", "pods", "-n", namespace, "--sort-by=.metadata.creationTimestamp", "-o", "name")
    return [line.strip()[4:] for line in out.splitlines() if line.strip().startswith("pod/")]
