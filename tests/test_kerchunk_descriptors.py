import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from xcube_cci_metadata_builder.descriptors import safe_descriptor_file_name
from xcube_cci_metadata_builder.jsonio import write_json
from xcube_cci_metadata_builder.kerchunk_descriptors import (
    build_kerchunk_descriptors,
    describe_kerchunk_reference,
)


class _Descriptor:
    def __init__(self, data_id):
        self.data_id = data_id

    def to_dict(self):
        return {
            "data_id": self.data_id,
            "data_type": "dataset",
            "attrs": {"title": self.data_id},
        }


class KerchunkDescriptorsTest(TestCase):
    def test_describe_kerchunk_reference_opens_reference_mapping(self):
        dataset = Mock()
        mapper = Mock()
        with patch(
            "xcube_cci_metadata_builder.kerchunk_descriptors.fsspec.get_mapper",
            return_value=mapper,
        ) as get_mapper, patch(
            "xcube_cci_metadata_builder.kerchunk_descriptors.xr.open_zarr",
            return_value=dataset,
        ) as open_zarr, patch(
            "xcube_cci_metadata_builder.kerchunk_descriptors.new_data_descriptor",
            return_value="descriptor",
        ) as new_descriptor:
            descriptor = describe_kerchunk_reference(
                data_id="kc-1",
                reference_path="https://example.com/kc-1.json",
            )

        self.assertEqual("descriptor", descriptor)
        get_mapper.assert_called_once_with(
            "reference://",
            fo="https://example.com/kc-1.json",
        )
        open_zarr.assert_called_once_with(mapper, consolidated=False)
        new_descriptor.assert_called_once_with("kc-1", dataset)
        dataset.close.assert_called_once()

    def test_build_kerchunk_descriptors_writes_matching_descriptors(self):
        with TemporaryDirectory() as tmp_dir:
            refs_path = Path(tmp_dir) / "refs.json"
            output_dir = Path(tmp_dir) / "descriptors"
            write_json(
                refs_path,
                {
                    "references": [
                        {
                            "data_id": "ESACCI-LST-mon-v1",
                            "odp_data_id": "odp-1",
                            "data_type": "dataset",
                            "reference_path": "https://example.com/ref-1.json",
                        },
                        {
                            "data_id": "ESACCI-SST-mon-v1",
                            "odp_data_id": "odp-2",
                            "data_type": "dataset",
                            "reference_path": "https://example.com/ref-2.json",
                        },
                    ]
                },
            )
            with patch(
                "xcube_cci_metadata_builder.kerchunk_descriptors.describe_kerchunk_reference",
                side_effect=lambda data_id, reference_path: _Descriptor(data_id),
            ) as describe:
                summary = build_kerchunk_descriptors(
                    references_path=refs_path,
                    descriptors_dir=output_dir,
                    name_pattern="LST-*",
                )

            descriptor_files = list(output_dir.glob("*.json"))
            self.assertEqual(1, summary.described)
            self.assertEqual(1, summary.skipped)
            self.assertEqual(0, summary.errors)
            self.assertEqual(1, describe.call_count)
            self.assertEqual(1, len(descriptor_files))
            payload = json.loads(descriptor_files[0].read_text(encoding="utf-8"))
            self.assertEqual("ESACCI-LST-mon-v1", payload["data_id"])

    def test_build_kerchunk_descriptors_resumes_existing_files(self):
        with TemporaryDirectory() as tmp_dir:
            refs_path = Path(tmp_dir) / "refs.json"
            output_dir = Path(tmp_dir) / "descriptors"
            write_json(
                refs_path,
                {
                    "references": [
                        {
                            "data_id": "kc-1",
                            "odp_data_id": "odp-1",
                            "data_type": "dataset",
                            "reference_path": "https://example.com/ref-1.json",
                        }
                    ]
                },
            )
            write_json(
                output_dir / safe_descriptor_file_name("kc-1"),
                {"data_id": "kc-1"},
            )
            with patch(
                "xcube_cci_metadata_builder.kerchunk_descriptors.describe_kerchunk_reference"
            ) as describe:
                summary = build_kerchunk_descriptors(
                    references_path=refs_path,
                    descriptors_dir=output_dir,
                )

            self.assertEqual(0, summary.described)
            self.assertEqual(1, summary.skipped)
            self.assertEqual(0, summary.errors)
            describe.assert_not_called()
