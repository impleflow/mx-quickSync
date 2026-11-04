#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Packs the working directory back into an EAR file - run ON THE POD by remoteCp.py.

1. each module from NESTED_MODULES: <unpack_dir> -> /tmp/maximo.unpack/<ear_entry>
2. /tmp/maximo.unpack -> /tmp/maximo.ear

Each archive is first written to a `.tmp` file and renamed to the target name only after it is closed -
an interrupted packing will not leave a truncated archive under the proper name.

Usage:
    python3 zipEar.py
"""

import os
import sys
import zipfile

from quickSyncCfg import MAXIMO_EAR_FILE, MAXIMO_UNPACK_DIR, NESTED_MODULES, log, timed

MANIFEST = "META-INF/MANIFEST.MF"
# Already compressed files - deflate gains nothing and costs time
STORED_EXTENSIONS = (".jar", ".war", ".rar", ".zip", ".gz", ".png", ".jpg", ".jpeg", ".gif")
# Fastest deflate level - packing time matters, not file size
COMPRESS_LEVEL = 1


def collect_entries(src_dir: str) -> list:
    """Returns a list of (path, archive name), directories with a trailing '/'. MANIFEST.MF goes first,
    because java.util.jar.JarInputStream looks for it only among the first entries."""
    entries = []
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        rel_root = os.path.relpath(root, src_dir).replace(os.sep, "/")
        if rel_root != ".":
            entries.append((root, rel_root + "/"))
        for name in sorted(files):
            arcname = name if rel_root == "." else f"{rel_root}/{name}"
            entries.append((os.path.join(root, name), arcname))

    first = [e for e in entries if e[1] in ("META-INF/", MANIFEST)]
    return first + [e for e in entries if e not in first]


def pack(src_dir: str, dest_file: str) -> None:
    log(f"Packing {src_dir} to {dest_file}")
    with timed("Done"):
        tmp_file = dest_file + ".tmp"
        with zipfile.ZipFile(
            tmp_file, "w", zipfile.ZIP_DEFLATED, compresslevel=COMPRESS_LEVEL, strict_timestamps=False
        ) as zf:
            for path, arcname in collect_entries(src_dir):
                stored = arcname.lower().endswith(STORED_EXTENSIONS)  # None: the default of the archive (deflate)
                zf.write(path, arcname, compress_type=zipfile.ZIP_STORED if stored else None)
        os.replace(tmp_file, dest_file)


def main() -> None:
    if not os.path.isdir(MAXIMO_UNPACK_DIR):
        sys.exit(f"Directory {MAXIMO_UNPACK_DIR} is missing - run unZipEar.py first")

    with timed("Packing finished"):
        for module in NESTED_MODULES:
            if not os.path.isdir(module.unpack_dir):
                sys.exit(
                    f"Directory {module.unpack_dir} is missing - delete {MAXIMO_UNPACK_DIR} and run unZipEar.py again"
                )
            pack(module.unpack_dir, os.path.join(MAXIMO_UNPACK_DIR, module.ear_entry))

        pack(MAXIMO_UNPACK_DIR, MAXIMO_EAR_FILE)


if __name__ == "__main__":
    main()
