#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Copies classes to one specific pod and swaps the EAR

Logic of sync() (parameters come from the function call; the configuration is read by quickSync.py):
1. Uploads quickSyncCfg.py, unZipEar.py, zipEar.py to the pod
2. Runs unZipEar.py (skipped on the pod if /tmp/maximo.unpack already exists)
3. Copies the compiled classes of each module from NESTED_MODULES (that has an entry in classes_dirs) into the
   unpacked directories in /tmp
4. Runs zipEar.py -> /tmp/maximo.ear
5. Replaces ear_location with /tmp/maximo.ear (as root, via `oc debug node` + `nsenter`,
   because apps/ is not writable for oc exec/oc cp - see README, "Ustalenia" section)
"""

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPTS_DIR.parent  # quickSync/: the script run by the user, podScripts/
# scripts uploaded to the pod (they cannot be run locally); quickSyncCfg.py is also imported here
POD_SCRIPTS_SRC = APP_DIR / "podScripts"
POD_SCRIPTS = ["quickSyncCfg.py", "unZipEar.py", "zipEar.py"]

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(POD_SCRIPTS_SRC))
import ocUtils  # noqa: E402
from quickSyncCfg import (  # noqa: E402
    MAXIMO_EAR_FILE,
    NESTED_MODULES,
    POD_SCRIPTS_DIR,
    log,
    timed,
)


@dataclass(frozen=True)
class PodTarget:
    """The pod container quickSync works on, and the temporary kubeconfig of the `oc` session."""

    kubeconfig: str
    namespace: str
    pod: str
    container: str
    node: str


def oc(target: PodTarget, *args: str, cwd=None) -> None:
    """Runs `oc` with its output shown live (the scripts on the pod report their progress); exits on failure."""
    log(f"$ oc {' '.join(args)}")
    ocUtils.oc(target.kubeconfig, *args, cwd=cwd, check=True, capture=False)


def oc_exec(target: PodTarget, *args: str) -> None:
    oc(target, "exec", "-n", target.namespace, target.pod, "-c", target.container, "--", *args)


def oc_cp_to_pod(target: PodTarget, local_dir: Path, local_name: str, remote_path: str) -> None:
    # cwd + relative name instead of a full path: on Windows oc cp mistakes the drive letter colon for a separator
    remote = f"{target.namespace}/{target.pod}:{remote_path}"
    oc(target, "cp", local_name, remote, "-c", target.container, cwd=str(local_dir))


def upload_scripts(target: PodTarget) -> None:
    oc_exec(target, "mkdir", "-p", POD_SCRIPTS_DIR)
    for name in POD_SCRIPTS:
        oc_cp_to_pod(target, POD_SCRIPTS_SRC, name, f"{POD_SCRIPTS_DIR}/{name}")


def copy_classes(target: PodTarget, local_dir: Path, remote_dir: str) -> None:
    if not local_dir.exists():
        log(f"Skipping {remote_dir} - {local_dir} does not exist locally")
        return
    log(f"Copying {local_dir} to {remote_dir}")
    with timed("Done"):
        oc_exec(target, "mkdir", "-p", remote_dir)
        oc_cp_to_pod(target, local_dir, ".", remote_dir)


def run_as_root_in_container(target: PodTarget, shell_script: str) -> None:
    """Runs shell_script as root in the container namespace (`oc debug node` + `nsenter`)."""
    script = (
        "set -e; "
        f"POD_ID=$(crictl pods --name {shlex.quote(target.pod)} --namespace {shlex.quote(target.namespace)} "
        "--state Ready -q | head -1); "
        f'CID=$(crictl ps --pod "$POD_ID" --name {shlex.quote(target.container)} --state Running -q | head -1); '
        "PID=$(crictl inspect \"$CID\" | grep -oE '\"pid\":[[:space:]]*[0-9]+' | head -1 | grep -oE '[0-9]+'); "
        f'nsenter -t "$PID" -m -u -i -n -p -- sh -c {shlex.quote(shell_script)}'
    )
    oc(target, "debug", f"node/{target.node}", "--", "chroot", "/host", "sh", "-c", script)


def swap_ear(target: PodTarget, ear_location: str) -> None:
    """Replaces ear_location with /tmp/maximo.ear.

    On the first swap on a given pod the original is kept as <ear>.bak (hard link - without
    copying 2.35 GB). /tmp and apps/ are on the same filesystem, so the final `mv` is an atomic
    rename - Liberty will never see a partially written file.
    """
    ear = shlex.quote(ear_location)
    bak = shlex.quote(ear_location + ".bak")
    new = shlex.quote(MAXIMO_EAR_FILE)
    swap_chain = (
        "set -e; "
        f"test -f {ear}; "
        f"chown --reference={ear} {new}; "
        f"chmod --reference={ear} {new}; "
        f"[ -e {bak} ] || ln {ear} {bak} || cp -p {ear} {bak}; "
        f"mv {new} {ear}"
    )
    run_as_root_in_container(target, swap_chain)


def sync(target: PodTarget, ear_location: str, maximo_smp_dir: Path, classes_dirs: dict) -> None:
    """classes_dirs: module key (NestedModule.config_key) -> directory with the compiled classes,
    relative to maximo_smp_dir."""
    log(f"=== {target.namespace}/{target.pod} ({target.container}) ===")
    with timed(f"Pod {target.pod} synchronized"):
        log("Uploading scripts to the pod")
        upload_scripts(target)

        oc_exec(target, "python3", "-u", f"{POD_SCRIPTS_DIR}/unZipEar.py", ear_location)

        for module in NESTED_MODULES:
            classes_dir = classes_dirs.get(module.config_key)
            if not classes_dir:
                log(f"Skipping {module.config_key} - no classes directory configured (tools.quickSync.classesDir)")
                continue
            remote_dir = f"{module.unpack_dir}/{module.classes_dest}" if module.classes_dest else module.unpack_dir
            copy_classes(target, maximo_smp_dir / classes_dir, remote_dir)

        oc_exec(target, "python3", "-u", f"{POD_SCRIPTS_DIR}/zipEar.py")

        log(f"Replacing {ear_location} with {MAXIMO_EAR_FILE}")
        with timed("Done"):
            swap_ear(target, ear_location)
