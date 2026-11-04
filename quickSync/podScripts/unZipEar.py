#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Unpacks the EAR into a working directory in /tmp

Usage:
    python3 unZipEar.py <ear_path>
"""

import os
import shutil
import sys
import zipfile

from quickSyncCfg import MAXIMO_UNPACK_DIR, NESTED_MODULES, log, timed


def extract(src: str, dest_dir: str, label_src: str, label_dest: str) -> None:
    log(f"Unpacking {label_src} to {label_dest}")
    with timed("Done"):
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        with zipfile.ZipFile(src) as zf:
            zf.extractall(dest_dir)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <ear_path>")
    ear_path = sys.argv[1]

    if os.path.exists(MAXIMO_UNPACK_DIR):
        log(f"Directory {MAXIMO_UNPACK_DIR} exists. Step skipped")
        return

    if os.path.isdir(ear_path):
        sys.exit(
            f"{ear_path} is a directory, not an EAR file (leftover from quickSync v2?). "
            "Delete the pod so that the operator recreates it from a fresh image."
        )

    with timed("Unpacking finished"):
        partial_dir = MAXIMO_UNPACK_DIR + ".partial"
        extract(ear_path, partial_dir, ear_path, MAXIMO_UNPACK_DIR)

        for module in NESTED_MODULES:
            module_path = os.path.join(partial_dir, module.ear_entry)
            if not os.path.isfile(module_path):
                sys.exit(f"{module.ear_entry} not found in {ear_path}")
            label_src = os.path.join(MAXIMO_UNPACK_DIR, module.ear_entry)
            extract(module_path, module.unpack_dir, label_src, module.unpack_dir)

        os.rename(partial_dir, MAXIMO_UNPACK_DIR)


if __name__ == "__main__":
    main()
