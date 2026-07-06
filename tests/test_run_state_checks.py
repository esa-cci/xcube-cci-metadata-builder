from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import xarray as xr
from xcube_cci_metadata_builder.result_store import ResultStore
import xcube_cci_metadata_builder.run_state_checks as run_state_checks_module
from xcube_cci_metadata_builder.run_state_checks import run_state_checks


class _Descriptor:
    data_type = "dataset"
    data_vars = {"mass": object()}
    attrs = {"title": "Dataset test"}


class _FakeStore:
    def __init__(self):
        self.opened = []

    def list_data_ids(self, data_type=None):
        return ["id-1", "id-2"]

    def describe_data(self, data_id, data_type=None):
        return _Descriptor()

    def open_data(self, data_id, **open_params):
        self.opened.append((data_id, open_params))
        return xr.Dataset({"mass": ("x", [1, 2])})


class RunStateChecksTest(TestCase):
    def test_run_state_checks_persists_results_and_resumes(self):
        with TemporaryDirectory() as tmp_dir:
            result_store = ResultStore(Path(tmp_dir))
            store = _FakeStore()

            summary = run_state_checks(
                store=store,
                result_store=result_store,
                data_types=("dataset",),
            )
            resumed = run_state_checks(
                store=store,
                result_store=result_store,
                data_types=("dataset",),
            )

            self.assertEqual(2, summary.checked)
            self.assertEqual(0, summary.errors)
            self.assertEqual(0, summary.skipped)
            self.assertEqual(0, resumed.checked)
            self.assertEqual(2, resumed.skipped)
            self.assertEqual(2, len(list(result_store.iter_results())))

    def test_run_state_checks_uses_explicit_data_ids_without_listing(self):
        class Store(_FakeStore):
            def get_data_ids(self, data_type=None):
                raise AssertionError("data IDs should not be listed")

        with TemporaryDirectory() as tmp_dir:
            store = Store()
            summary = run_state_checks(
                store=store,
                result_store=ResultStore(Path(tmp_dir)),
                data_types=("dataset",),
                data_ids=("explicit-id",),
            )

            self.assertEqual(1, summary.checked)

    def test_run_state_checks_honors_limit(self):
        with TemporaryDirectory() as tmp_dir:
            result_store = ResultStore(Path(tmp_dir))
            store = _FakeStore()

            summary = run_state_checks(
                store=store,
                result_store=result_store,
                data_types=("dataset",),
                limit=1,
            )

            self.assertEqual(1, summary.checked)
            self.assertEqual(1, len(list(result_store.iter_results())))

    def test_run_state_checks_logs_current_data_id(self):
        with TemporaryDirectory() as tmp_dir:
            with self.assertLogs(run_state_checks_module.LOG, level="INFO") as cm:
                run_state_checks(
                    store=_FakeStore(),
                    result_store=ResultStore(Path(tmp_dir)),
                    data_types=("dataset",),
                    limit=1,
            )

            self.assertIn(
                "Checking dataset data ID 1/2: id-1",
                "\n".join(cm.output),
            )

    def test_run_state_checks_logs_skipped_results(self):
        with TemporaryDirectory() as tmp_dir:
            result_store = ResultStore(Path(tmp_dir))
            store = _FakeStore()
            run_state_checks(
                store=store,
                result_store=result_store,
                data_types=("dataset",),
            )

            with self.assertLogs(run_state_checks_module.LOG, level="INFO") as cm:
                summary = run_state_checks(
                    store=store,
                    result_store=result_store,
                    data_types=("dataset",),
                )

            self.assertEqual(2, summary.skipped)
            self.assertTrue(
                any("Skipped 1 existing result(s)" in item for item in cm.output)
            )
