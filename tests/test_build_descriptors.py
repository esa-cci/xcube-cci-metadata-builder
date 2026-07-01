import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.build_descriptors import (
    build_descriptors,
    data_id_matches_pattern,
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


class _Store:
    def __init__(self):
        self.described = []

    def list_data_ids(self, data_type=None):
        return [
            "esacci.LST.mon.TERRA.MODIS.v4",
            "esacci.LST.day.TERRA.MODIS.v4",
            "esacci.SST.mon.ATSR.v3",
        ]

    def describe_data(self, data_id, data_type=None):
        self.described.append((data_id, data_type))
        return _Descriptor(data_id)


class BuildDescriptorsTest(TestCase):
    def test_data_id_matches_pattern_matches_full_id_and_contained_fragment(self):
        self.assertTrue(
            data_id_matches_pattern(
                "esacci.LST.mon.TERRA.MODIS.v4",
                "esacci.LST.mon.*.v4",
            )
        )
        self.assertTrue(
            data_id_matches_pattern(
                "esacci.LST.mon.TERRA.MODIS.v4",
                "LST.mon.*.v4",
            )
        )
        self.assertFalse(
            data_id_matches_pattern(
                "esacci.LST.day.TERRA.MODIS.v4",
                "LST.mon.*.v4",
            )
        )

    def test_build_descriptors_writes_matching_descriptors_to_registry(self):
        with TemporaryDirectory() as tmp_dir:
            store = _Store()

            summary = build_descriptors(
                store=store,
                registry_dir=Path(tmp_dir),
                store_id="esa-cci",
                data_types=("dataset",),
                name_pattern="LST.mon.*.v4",
            )

            descriptor_files = list(
                (Path(tmp_dir) / "descriptors" / "esa-cci").glob("*.json")
            )
            self.assertEqual(1, summary.described)
            self.assertEqual(2, summary.skipped)
            self.assertEqual(0, summary.errors)
            self.assertEqual(
                [("esacci.LST.mon.TERRA.MODIS.v4", "dataset")],
                store.described,
            )
            self.assertEqual(1, len(descriptor_files))
            descriptor = json.loads(descriptor_files[0].read_text(encoding="utf-8"))
            self.assertEqual("esacci.LST.mon.TERRA.MODIS.v4", descriptor["data_id"])

    def test_build_descriptors_honors_limit(self):
        with TemporaryDirectory() as tmp_dir:
            store = _Store()

            summary = build_descriptors(
                store=store,
                registry_dir=Path(tmp_dir),
                store_id="esa-cci",
                data_types=("dataset",),
                limit=2,
            )

            self.assertEqual(2, summary.described)
            self.assertEqual(0, summary.errors)
            self.assertEqual(2, len(store.described))
