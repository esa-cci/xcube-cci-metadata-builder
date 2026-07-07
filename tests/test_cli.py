from argparse import Namespace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from xcube_cci_metadata_builder.cli import (
    _parse_count,
    _run_checks,
    _run_checks_supervised,
    _run_checks_child_command,
)


class CliTest(TestCase):
    def test_parse_count_reads_cli_summary_line(self):
        self.assertEqual(12, _parse_count("checked: 12\nskipped: 3\n", "checked"))

    def test_run_checks_child_command_excludes_supervisor_flags(self):
        command = _run_checks_child_command(
            _args(
                store_id="esa-cci",
                results_dir=Path("work/results"),
                data_types=("dataset", "geodataframe"),
                timeout=120,
                retries=3,
                limit=5,
                data_ids=["id-1"],
            )
        )

        self.assertIn("run-checks", command)
        self.assertIn("--retries", command)
        self.assertIn("--run-once", command)
        self.assertNotIn("--timeout-retries", command)
        self.assertNotIn("--write-retries", command)
        self.assertNotIn("--max-restarts", command)

    def test_run_checks_uses_supervisor_by_default(self):
        with patch(
            "xcube_cci_metadata_builder.cli._run_checks_supervised",
            return_value=0,
        ) as run:
            exit_code = _run_checks(_args())

        self.assertEqual(0, exit_code)
        run.assert_called_once()

    def test_supervisor_stops_after_child_summary_even_with_errors(self):
        with patch(
            "xcube_cci_metadata_builder.cli._run_streamed_child",
            return_value=(1, "checked: 55\nskipped: 639\nerrors: 3\n"),
        ) as run:
            exit_code = _run_checks_supervised(_args())

        self.assertEqual(1, exit_code)
        self.assertEqual(1, run.call_count)

    def test_supervisor_restarts_child_without_summary(self):
        with patch(
            "xcube_cci_metadata_builder.cli._run_streamed_child",
            side_effect=[
                (-9, ""),
                (0, "checked: 0\nskipped: 694\nerrors: 0\n"),
            ],
        ) as run:
            exit_code = _run_checks_supervised(_args())

        self.assertEqual(0, exit_code)
        self.assertEqual(2, run.call_count)


def _args(**overrides):
    values = {
        "store_id": "esa-cci",
        "results_dir": Path("work/results"),
        "data_types": ("dataset",),
        "timeout": 120,
        "retries": 1,
        "limit": None,
        "data_ids": None,
        "no_resume": False,
        "run_once": False,
    }
    values.update(overrides)
    return Namespace(**values)
