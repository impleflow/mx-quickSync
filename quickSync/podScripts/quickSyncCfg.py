#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Shared configuration of the scripts run ON THE POD (unZipEar.py, zipEar.py).

Copied to the pod together with the other scripts by remoteCp.py. Does not read YAML configuration - only fixed
working paths inside the container. The local directories with the compiled classes are not here: they are
configured in tools.quickSync.classesDir (YAML), keyed by NestedModule.config_key.
"""

import time
from contextlib import contextmanager
from datetime import datetime
from typing import NamedTuple

# Directory on the pod where remoteCp.py uploads the scripts (quickSyncCfg.py, unZipEar.py, zipEar.py)
POD_SCRIPTS_DIR = "/tmp/quickSync"

# Unpacked EAR (working copy, never ends up in apps/)
MAXIMO_UNPACK_DIR = "/tmp/maximo.unpack"
# Repacked EAR - this is the file that replaces ear_location
MAXIMO_EAR_FILE = "/tmp/maximo.ear"


class NestedModule(NamedTuple):
    # Module name in the EAR
    ear_entry: str
    # Directory on the pod the module is unpacked to
    unpack_dir: str
    # Subdirectory of the unpacked module the classes are copied to ("" = module root)
    classes_dest: str
    # Key in tools.quickSync.classesDir (YAML); not read on the pod, only used by quickSync.py/remoteCp.py
    config_key: str = None


# Modules nested in the EAR - for each: unpack, copy classes, repack
NESTED_MODULES = [
    NestedModule(
        ear_entry="businessobjects.jar",
        unpack_dir="/tmp/businessobjects.unpack",
        classes_dest="",
        config_key="businessobjectsClassDir",
    ),
    NestedModule(
        ear_entry="maximouiweb.war",
        unpack_dir="/tmp/maximouiweb.unpack",
        classes_dest="WEB-INF/classes",
        config_key="maximouiwebClassDir",
    ),
]


def log(msg: str) -> None:
    # the same format as logUtils.log (the pod scripts cannot import it: only the three files above are uploaded)
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


@contextmanager
def timed(label: str):
    """Logs `<label> in <seconds> s` when the block finishes without an error."""
    start = time.perf_counter()
    yield
    log(f"{label} in {time.perf_counter() - start:.1f} s")
