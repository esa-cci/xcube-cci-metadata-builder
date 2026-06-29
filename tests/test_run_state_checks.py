from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.result_store import ResultStore
from xcube_cci_metadata_builder.run_state_checks import run_state_checks


class _Descriptor:
    data_type = "vectordatacube"
    data_vars = {"mass": object()}
    attrs = {"title": "Vector test"}


class _FakeStore:
    def __init__(self):
        self.opened = []

    def list_data_ids(self, data_type=None):
        return ["id-1", "id-2"]

    def describe_data(self, data_id, data_type=None):
        return _Descriptor()
        self.opened.append((data_id, open_params))

    def open_data(self, data_id, **open_params):
        return object()


class RunStateChecksTest(TestCase):
    def test_run_state_checks_persists_results_and_resumes(self):
        with TemporaryDirectory() as tmp_dir:
            result_store = ResultStore(Path(tmp_dir))
            store = _FakeStore()

            summary = run_state_checks(
                store=store,
                result_store=result_store,
                data_types=("vectordatacube",),
            )
            resumed = run_state_checks(
                store=store,
                result_store=result_store,
                data_types=("vectordatacube",),
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
                data_types=("vectordatacube",),
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
                data_types=("vectordatacube",),
                limit=1,
            )

            self.assertEqual(1, summary.checked)
            self.assertEqual(1, len(list(result_store.iter_results())))
