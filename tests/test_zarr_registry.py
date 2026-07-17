import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.descriptors import safe_descriptor_file_name
from xcube_cci_metadata_builder.jsonio import write_json
from xcube_cci_metadata_builder.registry_build import (
    ZarrMapping,
    add_zarr_to_registry,
    read_zarr_mappings,
)

CANONICAL_ID = "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.1-0.r1"


class _Store:
    def describe_data(self, data_id, data_type=None):
        return _Descriptor(data_id)


class _FailingStore:
    def describe_data(self, data_id, data_type=None):
        raise AssertionError("Existing descriptors must be reused")


class _Descriptor:
    def __init__(self, data_id):
        self.data_id = data_id

    def to_dict(self):
        return {"data_id": self.data_id, "data_type": "dataset"}


class ZarrRegistryTest(TestCase):
    def test_read_zarr_mappings_trims_csv_fields(self):
        with TemporaryDirectory() as tmp_dir:
            mapping_path = _write_mapping(Path(tmp_dir), "dataset.zarr")

            mappings = read_zarr_mappings(mapping_path)

        self.assertEqual([ZarrMapping("dataset.zarr", CANONICAL_ID)], mappings)

    def test_add_zarr_to_registry_builds_missing_descriptor(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            mapping_path = _write_mapping(root, "dataset.zarr")

            add_zarr_to_registry(
                store=_Store(),
                registry_dir=root,
                mapping_path=mapping_path,
            )

            descriptor_path = _descriptor_path(root, "dataset.zarr")
            self.assertTrue(descriptor_path.is_file())

    def test_existing_descriptor_creates_entry_missing_from_odp_registry(self):
        """Regression: mapped custom Zarr data must not require an ODP entry."""

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            mapping_path = _write_mapping(root, "custom.zarr")
            write_json(
                _descriptor_path(root, "custom.zarr"),
                {"data_id": "custom.zarr", "data_type": "dataset"},
            )

            add_zarr_to_registry(
                store=_FailingStore(),
                registry_dir=root,
                mapping_path=mapping_path,
            )

            registry = json.loads((root / "registry.json").read_text())
            self.assertEqual(CANONICAL_ID, registry["datasets"][0]["canonical_id"])

    def test_missing_descriptor_is_skipped_without_store(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            mapping_path = _write_mapping(root, "missing.zarr")

            summary = add_zarr_to_registry(
                store=None,
                registry_dir=root,
                mapping_path=mapping_path,
            )

            self.assertEqual(1, summary.skipped)
            self.assertEqual(0, summary.errors)
            self.assertFalse((root / "registry.json").exists())


def _write_mapping(root: Path, data_id: str) -> Path:
    path = root / "mapping"
    path.write_text(f"{data_id}, {CANONICAL_ID}\n", encoding="utf-8")
    return path


def _descriptor_path(root: Path, data_id: str) -> Path:
    return (
        root
        / "descriptors"
        / "esa-cci-zarr"
        / safe_descriptor_file_name(data_id)
    )
