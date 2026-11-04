#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""QuickSync - quick synchronization of businessobjects/maximouiweb classes with a Manage pod.

Runs LOCALLY, only on development environments (environments.<env>.quick_sync: true in config.yaml)
and only on the `all` node - on the other roles (cron, ui, ...) the directory layout is different and not supported.
Reads the configuration (config.yaml / secrets.yaml / local.yaml - see README.md), logs in to OC
(into a temporary kubeconfig), determines the pod (and its node), then delegates all work on the pod to remoteCp.sync().

Usage:
    python quickSync.py <env>
    python quickSync.py demo
    python quickSync.py demo --pod demo-demo-all-5d7c9b-abcde
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Manage node handled by quickSync (key in environments.<env>.nodes)
NODE_NAME = "all"
# Full path to the EAR in the `all` node container (the same in every MAS environment)
EAR_LOCATION = "/opt/ibm/wlp/usr/servers/defaultServer/apps/maximo-all.ear"

sys.path.insert(0, str(SCRIPT_DIR / "scripts"))  # the modules that are not run directly
sys.path.insert(0, str(SCRIPT_DIR / "podScripts"))  # quickSyncCfg.py lives with the scripts uploaded to the pod
import loadConfig  # noqa: E402
import ocUtils  # noqa: E402
import remoteCp  # noqa: E402
from logUtils import run_main  # noqa: E402
from quickSyncCfg import NESTED_MODULES, log  # noqa: E402


def find_pod(kubeconfig: str, namespace: str, pod_prefix: str, only_pod: str = None) -> str:
    prefix = f"{pod_prefix}-"
    matches = [n for n in ocUtils.pod_names(kubeconfig, namespace) if n.startswith(prefix)]
    if only_pod:
        if only_pod not in matches:
            sys.exit(f"Pod '{only_pod}' does not match prefix '{prefix}'. Matching: {matches or '(none)'}")
        return only_pod
    if not matches:
        sys.exit(f"No pod with prefix '{prefix}' found in namespace '{namespace}'.")
    if len(matches) > 1:
        sys.exit(f"More than one pod matches prefix '{prefix}': {matches}. Pick one: --pod <name>.")
    return matches[0]


def find_node(kubeconfig: str, namespace: str, pod: str) -> str:
    node = ocUtils.oc_ok(kubeconfig, "get", "pod", pod, "-n", namespace, "-o", "jsonpath={.spec.nodeName}").strip()
    if not node:
        sys.exit(f"Could not determine the node (spec.nodeName) of pod {pod}.")
    return node


def classes_dirs(tool_cfg: dict) -> dict:
    """tools.quickSync.classesDir: module key (NestedModule.config_key) -> compiled classes directory.

    The paths are relative to maximo_smp_dir. A module without an entry is only unpacked and repacked.
    """
    where = "tools.quickSync"
    section = loadConfig.require(tool_cfg, "classesDir", where)
    if not isinstance(section, dict):
        sys.exit(f"{where}.classesDir must map a module name to a directory.")
    known = [module.config_key for module in NESTED_MODULES]
    unknown = sorted(set(section) - set(known))
    if unknown:
        sys.exit(f"Unknown module(s) in {where}.classesDir: {', '.join(unknown)}. Known modules: {', '.join(known)}")
    return section


def main() -> None:
    config = loadConfig.load_config(SCRIPT_DIR)
    parser = argparse.ArgumentParser(description="Synchronizes classes with a Manage pod.")
    parser.add_argument("env", choices=config.environment_names(), help="environment from config.yaml")
    parser.add_argument("--pod", help="only this pod (full name)")
    args = parser.parse_args()

    env_cfg = config.environment(args.env)
    where = f"environments.{args.env}"
    if env_cfg.get("quick_sync") is not True:
        sys.exit(
            f"Environment '{args.env}' does not have {where}.quick_sync: true - quickSync works only on "
            f"development environments."
        )
    node_cfg = (env_cfg.get("nodes") or {}).get(NODE_NAME)
    if not node_cfg:
        sys.exit(
            f"Missing {where}.nodes.{NODE_NAME} in the configuration - quickSync supports only the '{NODE_NAME}' node."
        )
    node_where = f"{where}.nodes.{NODE_NAME}"
    server = loadConfig.require(env_cfg, "server", where)
    namespace = loadConfig.require(env_cfg, "manage_namespace", where)
    pod_prefix = loadConfig.require(node_cfg, "pod", node_where)
    container = node_cfg.get("container") or "all"
    login_args = ocUtils.require_login(env_cfg.get("oc_auth"), args.env, env_cfg.get("oc_skip_tls_verify", True))

    maximo_smp_dir = config.path("maximo_smp_dir", required=True)
    classes = classes_dirs(config.tool("quickSync", args.env))

    log(f"oc login {server}")
    with ocUtils.oc_session(server, login_args) as kubeconfig:
        pod = find_pod(kubeconfig, namespace, pod_prefix, args.pod)
        node = find_node(kubeconfig, namespace, pod)
        log(f"Pod: {pod}, node: {node}")
        target = remoteCp.PodTarget(kubeconfig, namespace, pod, container, node)
        remoteCp.sync(target, EAR_LOCATION, maximo_smp_dir, classes)

    log("Wait for Liberty to reload the application")


if __name__ == "__main__":
    run_main(main)
