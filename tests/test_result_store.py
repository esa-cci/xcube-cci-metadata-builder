from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.result_store import (
    BuilderResult,
    ResultStore,
    safe_result_file_name,
)


class ResultStoreTest(TestCase):
    def test_safe_result_file_name_is_stable_and_json(self):
        data_id = "esacci.TEST/with unsafe chars"

        name = safe_result_file_name(data_id)

        self.assertEqual(name, safe_result_file_name(data_id))
        self.assertTrue(name.endswith(".json"))
        self.assertNotIn("/", name)

    def test_result_store_writes_one_file_per_result(self):
        with TemporaryDirectory() as tmp_dir:
            store = ResultStore(Path(tmp_dir))
            result = BuilderResult(
                data_id="esacci.TEST",
                data_type="dataset",
                status="ok",
                state_entry={
                    "data_type": "dataset",
                    "verification_flags": ["open"],
                    "title": "Test",
                },
            )

            path = store.write_result(result)

            self.assertTrue(path.is_file())
            self.assertTrue(store.has_result("dataset", "esacci.TEST"))
            self.assertEqual([result], list(store.iter_results()))
