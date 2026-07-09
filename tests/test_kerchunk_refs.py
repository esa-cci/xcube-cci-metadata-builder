import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from xcube_cci_metadata_builder.kerchunk_refs import (
    collect_kerchunk_references,
    ref_path_to_data_id,
)


class KerchunkRefsTest(TestCase):
    def test_ref_path_to_data_id_uses_json_file_stem(self):
        self.assertEqual(
            "ESACCI-TEST-fv1.0_kr1.0",
            ref_path_to_data_id(
                "https://example.com/kerchunk/ESACCI-TEST-fv1.0_kr1.0.json"
            ),
        )

    def test_collect_kerchunk_references_writes_deduplicated_work_json(self):
        entries = {
            "dataset": [
                {
                    "data_id": "ref-1",
                    "odp_data_id": "odp-1",
                    "data_type": "dataset",
                    "reference_path": "https://example.com/ref-1.json",
                },
                {
                    "data_id": "ref-1",
                    "odp_data_id": "odp-1",
                    "data_type": "dataset",
                    "reference_path": "https://example.com/ref-1.json",
                },
            ],
            "geodataframe": [
                {
                    "data_id": "ref-2",
                    "odp_data_id": "odp-2",
                    "data_type": "geodataframe",
                    "reference_path": "https://example.com/ref-2.json",
                }
            ],
        }

        def collect_type(data_type, user_agent=""):
            return entries[data_type]

        with TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "kerchunk_refs.json"
            with patch(
                "xcube_cci_metadata_builder.kerchunk_refs.collect_kerchunk_references_for_type",
                side_effect=collect_type,
            ):
                summary = collect_kerchunk_references(
                    output_path=output,
                    data_types=("dataset", "geodataframe"),
                )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(2, summary.references)
            self.assertEqual(2, len(payload["references"]))
            self.assertEqual("odp-1", payload["references"][0]["odp_data_id"])

    def test_collect_kerchunk_references_honors_limit(self):
        def collect_type(data_type, user_agent=""):
            return [
                {
                    "data_id": "ref-1",
                    "odp_data_id": "odp-1",
                    "data_type": data_type,
                    "reference_path": "https://example.com/ref-1.json",
                }
            ]

        with TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "kerchunk_refs.json"
            with patch(
                "xcube_cci_metadata_builder.kerchunk_refs.collect_kerchunk_references_for_type",
                side_effect=collect_type,
            ):
                summary = collect_kerchunk_references(
                    output_path=output,
                    data_types=("dataset", "geodataframe"),
                    limit=1,
                )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, summary.references)
            self.assertEqual(1, len(payload["references"]))
