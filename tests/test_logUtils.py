# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Impleflow Sp. z o.o.
import re

import logUtils
import pytest

STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d"


def run(main, **kwargs):
    """Runs run_main(main) and returns the exit code (0 when it returned)."""
    try:
        logUtils.run_main(main, **kwargs)
    except SystemExit as exit_request:
        return exit_request.code
    return 0


class TestLog:
    def test_every_line_starts_with_the_date_and_time(self, capsys):
        logUtils.log("first\nsecond")
        lines = capsys.readouterr().out.splitlines()
        assert [re.fullmatch(rf"({STAMP}) (.*)", line).group(2) for line in lines] == ["first", "second"]

    def test_empty_message_is_a_timestamp_only(self, capsys):
        logUtils.log()
        assert re.fullmatch(rf"{STAMP} \n", capsys.readouterr().out)

    def test_file_argument_redirects_the_output(self, capsys):
        logUtils.log("problem", logUtils.sys.stderr)
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err.endswith(" problem\n")


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("seconds", "text"),
        [(0.04, "0.0 sec"), (12.34, "12.3 sec"), (125, "2 min 05 sec"), (3725, "1 h 02 min 05 sec")],
    )
    def test_largest_units_are_used(self, seconds, text):
        assert logUtils.format_duration(seconds) == text


class TestRunMain:
    def test_success_is_reported_with_the_duration(self, capsys):
        assert run(lambda: None) == 0
        assert re.fullmatch(rf"{STAMP} Finished successfully in \d+\.\d sec\n", capsys.readouterr().out)

    def test_exit_with_zero_or_none_is_a_success(self, capsys):
        assert run(lambda: logUtils.sys.exit(0)) == 0
        assert run(lambda: logUtils.sys.exit(None)) == 0
        assert capsys.readouterr().out.count("Finished successfully") == 2

    def test_exit_with_a_message_logs_it_and_fails_with_code_1(self, capsys):
        assert run(lambda: logUtils.sys.exit("it broke")) == 1
        err = capsys.readouterr().err
        assert re.search(rf"{STAMP} ERROR: it broke\n", err)
        assert re.search(rf"{STAMP} Finished with an error \(exit code 1\) in \d+\.\d sec\n", err)

    def test_exit_code_is_kept(self, capsys):
        assert run(lambda: logUtils.sys.exit(2)) == 2
        assert "exit code 2" in capsys.readouterr().err

    def test_ok_codes_are_a_success_with_their_exit_code_kept(self, capsys):
        assert run(lambda: logUtils.sys.exit(1), ok_codes=(0, 1)) == 1
        captured = capsys.readouterr()
        assert "Finished successfully" in captured.out and captured.err == ""

    def test_exception_is_logged_with_the_traceback_and_fails(self, capsys):
        def main():
            raise ValueError("bad value")

        assert run(main) == 1
        err = capsys.readouterr().err
        assert "Traceback" in err and "ERROR: ValueError: bad value" in err and "Finished with an error" in err
        assert all(re.match(STAMP, line) for line in err.splitlines())

    def test_interrupt_fails_with_code_130(self, capsys):
        def main():
            raise KeyboardInterrupt

        assert run(main) == logUtils.INTERRUPTED_EXIT_CODE
        assert "ERROR: interrupted" in capsys.readouterr().err
