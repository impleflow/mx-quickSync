# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
"""Console messages that start with the date and time, and the summary of a finished command (result and duration)."""

import sys
import time
import traceback
from datetime import datetime

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
INTERRUPTED_EXIT_CODE = 130


def timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def log(text: object = "", file=None) -> None:
    """Prints `text` to stdout (or `file`); every line starts with the timestamp."""
    stream = file or sys.stdout  # looked up at the call time, so a redirected stdout is honoured
    for line in str(text).splitlines() or [""]:
        print(f"{timestamp()} {line}", file=stream, flush=True)


def format_duration(seconds: float) -> str:
    """12.3 sec, 2 min 05 sec, 1 h 02 min 05 sec."""
    if seconds < 60:
        return f"{seconds:.1f} sec"
    hours, rest = divmod(round(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {secs:02d} sec"
    return f"{minutes} min {secs:02d} sec"


def run_main(main, ok_codes: tuple = (0,)) -> None:
    """Runs `main()` and logs how the command ended: success or error, and how long it took.

    The command ends with an error when main() raises an exception or exits with a code other than those in
    `ok_codes` (e.g. `sys.exit("message")` is an error, the message is logged). The process exit code is kept.
    """
    start = time.monotonic()
    code = 0
    try:
        main()
    except SystemExit as exit_request:
        code = exit_request.code
        if isinstance(code, str):  # sys.exit("message")
            log(f"ERROR: {code}", sys.stderr)
            code = 1
        elif code is None:
            code = 0
    except KeyboardInterrupt:
        log("ERROR: interrupted", sys.stderr)
        code = INTERRUPTED_EXIT_CODE
    except Exception as error:
        log(traceback.format_exc().rstrip(), sys.stderr)
        log(f"ERROR: {type(error).__name__}: {error}", sys.stderr)
        code = 1
    took = format_duration(time.monotonic() - start)
    if code in ok_codes:
        log(f"Finished successfully in {took}")
    else:
        log(f"Finished with an error (exit code {code}) in {took}", sys.stderr)
    if code:
        sys.exit(code)
