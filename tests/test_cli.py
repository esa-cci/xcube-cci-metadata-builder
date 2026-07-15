from argparse import Namespace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from xcube_cci_metadata_builder.cli import (
    _add_kerchunk_to_registry,
    _build_kerchunk_descriptors,
    _build_kerchunk_descriptors_child_command,
    _build_kerchunk_descriptors_supervised,
    _build_info,
    _collect_kerchunk_refs,
    _parse_count,
    _run_checks,
    _run_checks_supervised,
    _run_checks_child_command,
    _render_registry,
    _validate_registry,
)


class CliTest(TestCase):
    def test_build_info_calls_builder(self):
        with patch("xcube_cci_metadata_builder.cli.build_info") as build:
            build.return_value.output_path = Path("registry/build_info.json")

            exit_code = _build_info(Namespace(registry_dir=Path("registry")))

        self.assertEqual(0, exit_code)
        build.assert_called_once_with(Path("registry"))

    def test_validate_registry_calls_validator(self):
        with patch("xcube_cci_metadata_builder.cli.validate_registry_artifacts") as validate:
            validate.return_value.datasets = 1
            validate.return_value.representations = 2
            validate.return_value.states = 3
            validate.return_value.descriptors = 2

            exit_code = _validate_registry(Namespace(registry_dir=Path("registry")))

        self.assertEqual(0, exit_code)
        validate.assert_called_once_with(Path("registry"))

    def test_render_registry_calls_renderer(self):
        with patch("xcube_cci_metadata_builder.cli.render_registry") as render:
            render.return_value.datasets = 1
            render.return_value.kerchunk_representations = 2
            render.return_value.zarr_representations = 3
            render.return_value.registry_path = Path("registry/registry.json")
            render.return_value.build_info_path = Path("registry/build_info.json")

            exit_code = _render_registry(
                Namespace(
                    registry_dir=Path("registry"),
                    store_id="esa-cci",
                    catalog_urls=None,
                    kerchunk_references=Path("refs.json"),
                    kerchunk_descriptors_dir=Path("kc-descriptors"),
                    zarr_mapping=Path("zarr-mapping"),
                )
            )

        self.assertEqual(0, exit_code)
        render.assert_called_once_with(
            Path("registry"),
            kerchunk_references_path=Path("refs.json"),
            kerchunk_descriptors_dir=Path("kc-descriptors"),
            zarr_mapping_path=Path("zarr-mapping"),
            store_id="esa-cci",
            catalog_urls_path=None,
        )

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

    def test_collect_kerchunk_refs_calls_builder(self):
        with patch(
            "xcube_cci_metadata_builder.cli.collect_kerchunk_references",
        ) as collect:
            collect.return_value.references = 2
            collect.return_value.output_path = Path("work/refs.json")

            exit_code = _collect_kerchunk_refs(
                Namespace(
                    output=Path("work/refs.json"),
                    data_types=("dataset",),
                    limit=2,
                )
            )

        self.assertEqual(0, exit_code)
        collect.assert_called_once_with(
            output_path=Path("work/refs.json"),
            data_types=("dataset",),
            limit=2,
        )

    def test_add_kerchunk_to_registry_calls_builder(self):
        with patch("xcube_cci_metadata_builder.cli.add_kerchunk_to_registry") as add:
            add.return_value.representations = 1
            add.return_value.descriptors = 1
            add.return_value.skipped = 0
            add.return_value.output_path = Path("registry.json")

            exit_code = _add_kerchunk_to_registry(
                Namespace(
                    registry_dir=Path("registry"),
                    references=Path("refs.json"),
                    descriptors_dir=Path("descriptors"),
                    store_id="esa-cci-kc",
                )
            )

        self.assertEqual(0, exit_code)
        add.assert_called_once_with(
            registry_dir=Path("registry"),
            references_path=Path("refs.json"),
            descriptors_dir=Path("descriptors"),
            store_id="esa-cci-kc",
        )

    def test_build_kerchunk_descriptors_calls_builder(self):
        with patch(
            "xcube_cci_metadata_builder.cli.build_kerchunk_descriptors",
        ) as build:
            build.return_value.described = 2
            build.return_value.skipped = 1
            build.return_value.errors = 0

            exit_code = _build_kerchunk_descriptors(
                Namespace(
                    references=Path("work/refs.json"),
                    output_dir=Path("work/descriptors"),
                    data_ids=["kc-1"],
                    name_pattern="kc-*",
                    limit=2,
                    no_resume=True,
                    run_once=True,
                )
            )

        self.assertEqual(0, exit_code)
        build.assert_called_once_with(
            references_path=Path("work/refs.json"),
            descriptors_dir=Path("work/descriptors"),
            data_ids=["kc-1"],
            name_pattern="kc-*",
            limit=2,
            resume=False,
        )

    def test_build_kerchunk_descriptors_uses_supervisor_by_default(self):
        with patch(
            "xcube_cci_metadata_builder.cli._build_kerchunk_descriptors_supervised",
            return_value=0,
        ) as run:
            exit_code = _build_kerchunk_descriptors(_kerchunk_args())

        self.assertEqual(0, exit_code)
        run.assert_called_once()

    def test_build_kerchunk_descriptors_child_command_keeps_resume_enabled(self):
        command = _build_kerchunk_descriptors_child_command(
            _kerchunk_args(
                references=Path("work/refs.json"),
                output_dir=Path("work/descriptors"),
                data_ids=["kc-1"],
                name_pattern="kc-*",
                limit=2,
            )
        )

        self.assertIn("build-kerchunk-descriptors", command)
        self.assertIn("--run-once", command)
        self.assertNotIn("--no-resume", command)
        self.assertIn("--references", command)
        self.assertIn("work/refs.json", command)
        self.assertIn("--output-dir", command)
        self.assertIn("work/descriptors", command)
        self.assertIn("--data-id", command)
        self.assertIn("kc-1", command)
        self.assertIn("--name-pattern", command)
        self.assertIn("kc-*", command)
        self.assertIn("--limit", command)
        self.assertIn("2", command)

    def test_build_kerchunk_descriptors_supervisor_stops_after_summary(self):
        with patch(
            "xcube_cci_metadata_builder.cli._run_streamed_child",
            return_value=(0, "described: 3\nskipped: 10\nerrors: 0\n"),
        ) as run:
            exit_code = _build_kerchunk_descriptors_supervised(_kerchunk_args())

        self.assertEqual(0, exit_code)
        self.assertEqual(1, run.call_count)

    def test_build_kerchunk_descriptors_supervisor_restarts_without_summary(self):
        with patch(
            "xcube_cci_metadata_builder.cli._run_streamed_child",
            side_effect=[
                (-9, "Killed\n"),
                (0, "described: 0\nskipped: 100\nerrors: 0\n"),
            ],
        ) as run:
            exit_code = _build_kerchunk_descriptors_supervised(_kerchunk_args())

        self.assertEqual(0, exit_code)
        self.assertEqual(2, run.call_count)

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


def _kerchunk_args(**overrides):
    values = {
        "references": Path("work/kerchunk_refs/esa-cci-kc-references.json"),
        "output_dir": Path("work/kerchunk_descriptors/esa-cci-kc"),
        "data_ids": None,
        "name_pattern": None,
        "limit": None,
        "no_resume": False,
        "run_once": False,
    }
    values.update(overrides)
    return Namespace(**values)
