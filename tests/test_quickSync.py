# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Tests of the pod selection logic and of the command wrappers (no cluster needed)."""

import subprocess
from types import SimpleNamespace

import ocUtils
import pytest
import remoteCp
from quickSyncCfg import timed

import quickSync

TARGET = remoteCp.PodTarget(kubeconfig="kc", namespace="ns", pod="pod-1", container="all", node="worker-1")


def completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


@pytest.fixture
def fake_run(monkeypatch):
    """Replaces subprocess.run; records the calls. Set `fake_run.result` per test."""
    state = SimpleNamespace(calls=[], result=completed())

    def run(cmd, **kwargs):
        state.calls.append(SimpleNamespace(cmd=cmd, **kwargs))
        return state.result

    monkeypatch.setattr(subprocess, "run", run)
    return state


class TestFindPod:
    @pytest.fixture
    def pods(self, monkeypatch):
        state = SimpleNamespace(names=[], calls=[])
        monkeypatch.setattr(ocUtils, "pod_names", lambda kc, ns: state.calls.append((kc, ns)) or state.names)
        return state

    def test_single_match(self, pods):
        pods.names = ["demo-all-1-abc", "demo-cron-1-xyz", "other-pod"]
        assert quickSync.find_pod("kc", "ns", "demo-all") == "demo-all-1-abc"

    def test_prefix_requires_dash_separator(self, pods):
        # 'demo-all' must not match 'demo-allocator-1-abc'
        pods.names = ["demo-allocator-1-abc"]
        with pytest.raises(SystemExit) as exc:
            quickSync.find_pod("kc", "ns", "demo-all")
        assert "No pod with prefix" in str(exc.value)

    def test_no_match_exits(self, pods):
        pods.names = ["something-else"]
        with pytest.raises(SystemExit) as exc:
            quickSync.find_pod("kc", "ns", "demo-all")
        assert "demo-all-" in str(exc.value)

    def test_multiple_matches_exit_and_suggest_pod_option(self, pods):
        pods.names = ["demo-all-1-abc", "demo-all-2-def"]
        with pytest.raises(SystemExit) as exc:
            quickSync.find_pod("kc", "ns", "demo-all")
        message = str(exc.value)
        assert "--pod" in message and "demo-all-1-abc" in message and "demo-all-2-def" in message

    def test_only_pod_selects_one_of_many(self, pods):
        pods.names = ["demo-all-1-abc", "demo-all-2-def"]
        assert quickSync.find_pod("kc", "ns", "demo-all", only_pod="demo-all-2-def") == "demo-all-2-def"

    def test_only_pod_must_match_prefix(self, pods):
        pods.names = ["demo-all-1-abc", "demo-cron-1-xyz"]
        with pytest.raises(SystemExit):
            quickSync.find_pod("kc", "ns", "demo-all", only_pod="demo-cron-1-xyz")

    def test_queries_the_right_namespace_with_the_session_kubeconfig(self, pods):
        pods.names = ["demo-all-1-abc"]
        quickSync.find_pod("kc", "mas-demo-manage", "demo-all")
        assert pods.calls == [("kc", "mas-demo-manage")]

    def test_oc_failure_reports_the_error_output(self, fake_run):
        fake_run.result = completed(stderr="Forbidden: pods is forbidden", returncode=1)
        with pytest.raises(SystemExit) as exc:
            quickSync.find_pod("kc", "ns", "demo-all")
        assert "Forbidden: pods is forbidden" in str(exc.value)


class TestFindNode:
    def test_returns_node_name(self, fake_run):
        fake_run.result = completed(stdout="worker-1\n")
        assert quickSync.find_node("kc", "ns", "pod-1") == "worker-1"
        assert fake_run.calls[0].env["KUBECONFIG"] == "kc"

    def test_empty_node_exits(self, fake_run):
        fake_run.result = completed(stdout="  \n")
        with pytest.raises(SystemExit) as exc:
            quickSync.find_node("kc", "ns", "pod-1")
        assert "pod-1" in str(exc.value)

    def test_oc_failure_reports_the_error_output(self, fake_run):
        fake_run.result = completed(stderr='pods "pod-1" not found', returncode=1)
        with pytest.raises(SystemExit) as exc:
            quickSync.find_node("kc", "ns", "pod-1")
        assert 'pods "pod-1" not found' in str(exc.value)


class TestOc:
    def test_logs_the_command_and_shows_the_output_live(self, fake_run, capsys):
        remoteCp.oc(TARGET, "get", "pods")
        call = fake_run.calls[0]
        assert call.cmd == ["oc", "get", "pods"] and call.capture_output is False
        assert call.env["KUBECONFIG"] == "kc"
        assert "$ oc get pods" in capsys.readouterr().out

    def test_failure_exits_with_exit_code(self, fake_run):
        fake_run.result = completed(returncode=3)
        with pytest.raises(SystemExit) as exc:
            remoteCp.oc(TARGET, "get", "pods")
        assert "exit code 3" in str(exc.value)

    def test_exec_and_cp_address_the_target_container(self, fake_run, tmp_path):
        remoteCp.oc_exec(TARGET, "ls")
        remoteCp.oc_cp_to_pod(TARGET, tmp_path, "a.py", "/tmp/a.py")
        assert fake_run.calls[0].cmd == ["oc", "exec", "-n", "ns", "pod-1", "-c", "all", "--", "ls"]
        assert fake_run.calls[1].cmd == ["oc", "cp", "a.py", "ns/pod-1:/tmp/a.py", "-c", "all"]
        assert fake_run.calls[1].cwd == str(tmp_path)


class TestTimed:
    def test_logs_the_duration_after_the_block(self, capsys):
        with timed("Step"):
            assert capsys.readouterr().out == ""
        assert " Step in " in capsys.readouterr().out

    def test_failed_block_is_not_reported_as_done(self, capsys):
        with pytest.raises(SystemExit):
            with timed("Step"):
                raise SystemExit("boom")
        assert capsys.readouterr().out == ""


class TestSwapEar:
    @pytest.fixture
    def swap_script(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            remoteCp, "run_as_root_in_container", lambda target, script: captured.update(target=target, script=script)
        )
        return captured

    def test_swap_is_atomic_and_keeps_backup(self, swap_script):
        remoteCp.swap_ear(TARGET, "/opt/app/maximo-all.ear")
        script = swap_script["script"]
        assert script.startswith("set -e; ")
        assert "ln /opt/app/maximo-all.ear /opt/app/maximo-all.ear.bak" in script
        assert "[ -e /opt/app/maximo-all.ear.bak ] ||" in script  # backup only once
        assert script.endswith("mv /tmp/maximo.ear /opt/app/maximo-all.ear")

    def test_permissions_are_copied_before_move(self, swap_script):
        remoteCp.swap_ear(TARGET, "/opt/app/maximo-all.ear")
        script = swap_script["script"]
        assert script.index("chown --reference") < script.index("mv ")
        assert script.index("chmod --reference") < script.index("mv ")

    def test_paths_with_spaces_are_quoted(self, swap_script):
        remoteCp.swap_ear(TARGET, "/opt/my app/x.ear")
        assert "'/opt/my app/x.ear'" in swap_script["script"]

    def test_target_is_passed_through(self, swap_script):
        remoteCp.swap_ear(TARGET, "/opt/app/x.ear")
        assert swap_script["target"] is TARGET


class TestRunAsRoot:
    @pytest.fixture
    def command(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(remoteCp, "oc", lambda target, *args, cwd=None: captured.update(args=args))
        return captured

    def test_script_targets_pod_container_and_node(self, command):
        remoteCp.run_as_root_in_container(TARGET, "echo hi")
        args = command["args"]
        assert args[:2] == ("debug", "node/worker-1")
        script = args[-1]
        assert "--name pod-1" in script and "--namespace ns" in script and "--name all" in script
        assert "nsenter" in script and "echo hi" in script

    def test_shell_metacharacters_in_names_are_quoted(self, command):
        remoteCp.run_as_root_in_container(remoteCp.PodTarget("kc", "ns", "pod; rm -rf /", "all", "w"), "true")
        assert "'pod; rm -rf /'" in command["args"][-1]


class TestPodScriptsLayout:
    def test_every_uploaded_script_exists_in_the_pod_scripts_directory(self):
        for name in remoteCp.POD_SCRIPTS:
            assert (remoteCp.POD_SCRIPTS_SRC / name).is_file(), name

    def test_pod_scripts_directory_contains_only_uploaded_scripts(self):
        present = {p.name for p in remoteCp.POD_SCRIPTS_SRC.glob("*.py")}
        assert present == set(remoteCp.POD_SCRIPTS)

    def test_scripts_are_uploaded_from_the_pod_scripts_directory(self, monkeypatch):
        uploaded = []
        monkeypatch.setattr(remoteCp, "oc_exec", lambda *a: None)
        monkeypatch.setattr(
            remoteCp,
            "oc_cp_to_pod",
            lambda target, local_dir, name, remote: uploaded.append((local_dir, name, remote)),
        )
        remoteCp.upload_scripts(TARGET)
        assert {d for d, _, _ in uploaded} == {remoteCp.POD_SCRIPTS_SRC}
        assert [n for _, n, _ in uploaded] == remoteCp.POD_SCRIPTS
        assert all(r == f"{remoteCp.POD_SCRIPTS_DIR}/{n}" for _, n, r in uploaded)


class TestClassesDirs:
    def test_returns_the_mapping(self):
        section = {"businessobjectsClassDir": "a/classes", "maximouiwebClassDir": "b/classes"}
        assert quickSync.classes_dirs({"classesDir": section}) == section

    def test_module_without_entry_is_allowed(self):
        assert quickSync.classes_dirs({"classesDir": {"maximouiwebClassDir": "b"}}) == {"maximouiwebClassDir": "b"}

    def test_missing_section_exits_naming_the_key(self):
        with pytest.raises(SystemExit) as exc:
            quickSync.classes_dirs({})
        assert "tools.quickSync.classesDir" in str(exc.value)

    def test_unknown_module_exits_and_lists_known_ones(self):
        with pytest.raises(SystemExit) as exc:
            quickSync.classes_dirs({"classesDir": {"typo.jar": "x"}})
        message = str(exc.value)
        assert "typo.jar" in message and "businessobjectsClassDir" in message and "maximouiwebClassDir" in message

    def test_non_mapping_exits(self):
        with pytest.raises(SystemExit):
            quickSync.classes_dirs({"classesDir": ["businessobjectsClassDir"]})

    def test_all_pod_modules_can_be_configured(self):
        names = {m.config_key for m in quickSync.NESTED_MODULES}
        assert quickSync.classes_dirs({"classesDir": {n: "x" for n in names}}).keys() == names


class TestSync:
    @pytest.fixture
    def steps(self, monkeypatch):
        calls = []
        monkeypatch.setattr(remoteCp, "upload_scripts", lambda target: calls.append("upload"))
        monkeypatch.setattr(remoteCp, "oc_exec", lambda target, *args: calls.append(args))
        monkeypatch.setattr(
            remoteCp, "copy_classes", lambda target, local, remote: calls.append(("copy", local, remote))
        )
        monkeypatch.setattr(remoteCp, "swap_ear", lambda target, ear: calls.append("swap"))
        return calls

    def test_runs_steps_in_order(self, steps, tmp_path):
        classes_dirs = {m.config_key: f"classes/{m.config_key}" for m in remoteCp.NESTED_MODULES}
        remoteCp.sync(TARGET, "/opt/x.ear", tmp_path, classes_dirs)

        assert steps[0] == "upload"
        assert steps[1][2].endswith("unZipEar.py") and steps[1][3] == "/opt/x.ear"
        copies = [c for c in steps if isinstance(c, tuple) and c[0] == "copy"]
        assert len(copies) == len(remoteCp.NESTED_MODULES)
        assert steps[-2][2].endswith("zipEar.py")
        assert steps[-1] == "swap"

    def test_classes_are_taken_from_the_configured_directory_below_smp_dir(self, steps, tmp_path):
        module = remoteCp.NESTED_MODULES[0]
        remoteCp.sync(TARGET, "/opt/x.ear", tmp_path, {module.config_key: "app/classes"})
        copies = [c[1:] for c in steps if isinstance(c, tuple) and c[0] == "copy"]
        remote = f"{module.unpack_dir}/{module.classes_dest}" if module.classes_dest else module.unpack_dir
        assert copies == [(tmp_path / "app" / "classes", remote)]

    def test_module_without_configured_directory_is_skipped(self, steps, tmp_path, capsys):
        remoteCp.sync(TARGET, "/opt/x.ear", tmp_path, {})
        assert not any(isinstance(c, tuple) and c[0] == "copy" for c in steps)
        assert "Skipping" in capsys.readouterr().out

    def test_copy_classes_skips_missing_local_dir(self, monkeypatch, tmp_path, capsys):
        executed = []
        monkeypatch.setattr(remoteCp, "oc_exec", lambda *a: executed.append(a))
        monkeypatch.setattr(remoteCp, "oc_cp_to_pod", lambda *a: executed.append(a))
        remoteCp.copy_classes(TARGET, tmp_path / "missing", "/tmp/x")
        assert executed == []
        assert "Skipping" in capsys.readouterr().out

    def test_copy_classes_copies_existing_dir(self, monkeypatch, tmp_path):
        executed = []
        monkeypatch.setattr(remoteCp, "oc_exec", lambda target, *args: executed.append(("exec", args)))
        monkeypatch.setattr(remoteCp, "oc_cp_to_pod", lambda target, *args: executed.append(("cp", args)))
        remoteCp.copy_classes(TARGET, tmp_path, "/tmp/x")
        assert executed == [("exec", ("mkdir", "-p", "/tmp/x")), ("cp", (tmp_path, ".", "/tmp/x"))]
