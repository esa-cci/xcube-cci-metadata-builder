import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.build_info import build_info
from xcube_cci_metadata_builder.constants import STATE_FILE_NAMES


class BuildInfoTest(TestCase):
    def test_build_info_counts_existing_artifacts(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(
                root / "registry.json",
                {
                    "datasets": [
                        {
                            "representations": [
                                {"store_id": "esa-cci"},
                                {"store_id": "esa-cci-zarr"},
                            ]
                        }
                    ]
                },
            )
            for file_name in STATE_FILE_NAMES.values():
                _write_json(root / "states" / file_name, {})
            _write_json(root / "states" / "dataset_states.json", {"id": {}})
            _write_json(root / "descriptors" / "esa-cci" / "id.json", {})

            summary = build_info(root, generated_at="2026-07-15T10:00:00Z")

            value = json.loads(summary.output_path.read_text())
            self.assertEqual(1, value["counts"]["registry_datasets"])
            self.assertEqual(2, value["counts"]["registry_representations"])
            self.assertEqual(1, value["counts"]["states_dataset"])
            self.assertEqual(1, value["counts"]["descriptors"])
            self.assertEqual(["esa-cci", "esa-cci-zarr"], value["source"]["store_ids"])


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
