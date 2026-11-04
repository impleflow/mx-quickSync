# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Tests of ocUtils.py; `subprocess.run` is faked - no `oc` and no cluster needed."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import ocUtils
import pytest


def completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


@pytest.fixture
def fake_run(monkeypatch):
    """Records the commands; set `fake_run.result` (or `fake_run.results` for consecutive calls) per test."""
    state = SimpleNamespace(calls=[], result=completed(), results=None)

    def run(cmd, **kwargs):
        state.calls.append(SimpleNamespace(cmd=cmd, **kwargs))
        return state.results.pop(0) if state.results else state.result

    monkeypatch.setattr(subprocess, "run", run)
    return state


class TestRun:
    def test_returns_the_result(self, fake_run):
        fake_run.result = completed(stdout="out")
        assert ocUtils.run("tool", "arg").stdout == "out"

    def test_passes_cwd_env_and_utf8_decoding(self, fake_run):
        ocUtils.run("tool", "arg", cwd="/work", env={"A": "1"})
        call = fake_run.calls[0]
        assert call.cmd == ["tool", "arg"] and call.cwd == "/work" and call.env == {"A": "1"}
        assert call.encoding == "utf-8" and call.errors == "replace" and call.capture_output is True

    def test_failure_exits_with_the_command_exit_code_and_stderr(self, fake_run):
        fake_run.result = completed(stderr="denied", returncode=3)
        with pytest.raises(SystemExit) as exc:
            ocUtils.run("tool", "arg")
        assert str(exc.value) == "tool arg failed (exit code 3):\ndenied"

    def test_failure_falls_back_to_stdout(self, fake_run):
        fake_run.result = completed(stdout="details", returncode=1)
        with pytest.raises(SystemExit) as exc:
            ocUtils.run("tool")
        assert "details" in str(exc.value)

    def test_failure_is_returned_without_check(self, fake_run):
        fake_run.result = completed(returncode=3)
        assert ocUtils.run("tool", check=False).returncode == 3

    def test_uncaptured_output_goes_to_the_console(self, fake_run):
        fake_run.result = completed(stdout=None, stderr=None, returncode=2)
        with pytest.raises(SystemExit) as exc:
            ocUtils.run("tool", capture=False)
        assert fake_run.calls[0].capture_output is False
        assert str(exc.value) == "tool failed (exit code 2)."

    def test_missing_executable_exits(self, monkeypatch):
        def missing(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", missing)
        with pytest.raises(SystemExit) as exc:
            ocUtils.run("tool", check=False)
        assert "`tool` not found in PATH" in str(exc.value)


class TestOc:
    def test_uses_the_given_kubeconfig_and_cwd(self, fake_run):
        ocUtils.oc("/tmp/kc", "cp", "f.zip", cwd="/work")
        call = fake_run.calls[0]
        assert call.cmd == ["oc", "cp", "f.zip"] and call.cwd == "/work"
        assert call.env["KUBECONFIG"] == "/tmp/kc"

    def test_oc_returns_a_failure_without_exiting(self, fake_run):
        fake_run.result = completed(returncode=1)
        assert ocUtils.oc("kc", "get", "pods").returncode == 1

    def test_oc_ok_returns_stdout(self, fake_run):
        fake_run.result = completed(stdout="out")
        assert ocUtils.oc_ok("kc", "get", "pods") == "out"

    def test_oc_ok_exits_with_stderr_on_failure(self, fake_run):
        fake_run.result = completed(stderr="denied", returncode=1)
        with pytest.raises(SystemExit) as exc:
            ocUtils.oc_ok("kc", "get", "pods")
        assert "oc get pods failed" in str(exc.value) and "denied" in str(exc.value)


class TestLogin:
    def test_arguments_are_split_like_a_shell(self, fake_run):
        ocUtils.login("kc", "https://api", "-u admin -p 'pa ss'")
        assert fake_run.calls[0].cmd == ["oc", "login", "https://api", "-u", "admin", "-p", "pa ss"]

    def test_failure_exits_without_the_credentials(self, fake_run):
        fake_run.result = completed(stderr="Unauthorized", returncode=1)
        with pytest.raises(SystemExit) as exc:
            ocUtils.login("kc", "https://api", "--token=SECRET")
        assert str(exc.value) == "oc login https://api failed:\nUnauthorized"

    def test_require_login_appends_skip_tls_verify_by_default(self):
        assert ocUtils.require_login("--token=x", "dev") == "--token=x --insecure-skip-tls-verify"

    def test_require_login_skip_tls_verify_false_leaves_arguments_untouched(self):
        assert ocUtils.require_login("--token=x", "dev", False) == "--token=x"

    def test_require_login_does_not_duplicate_an_already_present_flag(self):
        args = "--token=x --insecure-skip-tls-verify"
        assert ocUtils.require_login(args, "dev") == args

    @pytest.mark.parametrize("value", [None, ""])
    def test_require_login_names_the_key(self, value):
        with pytest.raises(SystemExit) as exc:
            ocUtils.require_login(value, "dev")
        assert "environments.dev.oc_auth" in str(exc.value) and "local.yaml" in str(exc.value)


class TestSession:
    def test_logs_in_to_a_temporary_kubeconfig_and_removes_it(self, fake_run):
        with ocUtils.oc_session("https://api", "--token=x") as kubeconfig:
            assert Path(kubeconfig).parent.is_dir()
            assert fake_run.calls[0].cmd == ["oc", "login", "https://api", "--token=x"]
            assert fake_run.calls[0].env["KUBECONFIG"] == kubeconfig
        assert not Path(kubeconfig).parent.exists()

    def test_failed_login_removes_the_kubeconfig(self, fake_run):
        fake_run.result = completed(stderr="Unauthorized", returncode=1)
        with pytest.raises(SystemExit):
            with ocUtils.oc_session("https://api", "--token=x"):
                pass
        assert not Path(fake_run.calls[0].env["KUBECONFIG"]).parent.exists()


class TestPodNames:
    def test_names_oldest_first_without_the_prefix(self, fake_run):
        fake_run.result = completed(stdout="pod/a-1\npod/a-2\n\n")
        assert ocUtils.pod_names("kc", "ns") == ["a-1", "a-2"]
        assert fake_run.calls[0].cmd[:5] == ["oc", "get", "pods", "-n", "ns"]
        assert "--sort-by=.metadata.creationTimestamp" in fake_run.calls[0].cmd

    def test_ignores_lines_of_other_kinds(self, fake_run):
        fake_run.result = completed(stdout="service/a-svc\npod/a-1\n")
        assert ocUtils.pod_names("kc", "ns") == ["a-1"]
