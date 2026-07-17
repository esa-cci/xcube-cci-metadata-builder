import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.descriptors import safe_descriptor_file_name
from xcube_cci_metadata_builder.registry_build import (
    add_kerchunk_to_registry,
    add_supersession_links,
    build_esa_cci_registry,
    build_esa_cci_registry_entries,
    derive_collection_id,
    normalize_version,
    parse_version_sort_key,
    read_catalog_urls,
)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class RegistryBuildTest(TestCase):
    def test_build_entries_from_esa_cci_descriptors(self):
        with TemporaryDirectory() as tmp_dir:
            registry_dir = Path(tmp_dir)
            data_id = (
                "esacci.AEROSOL.day.L3.AAI.multi-sensor.multi-platform."
                "MSAAI.1-7.r1"
            )
            descriptor = {
                "data_id": data_id,
                "data_type": "dataset",
                "bbox": [-10.0, -20.0, 30.0, 40.0],
                "time_range": ["2001-01-01", "2020-12-31"],
                "attrs": {
                    "title": "Descriptor title",
                    "ecv": "AEROSOL",
                    "product_version": "1.7",
                    "catalog_url": "https://catalogue.ceda.ac.uk/uuid/test-uuid",
                },
            }
            descriptor_path = (
                registry_dir
                / "descriptors"
                / "esa-cci"
                / safe_descriptor_file_name(data_id)
            )
            _write_json(descriptor_path, descriptor)
            _write_json(
                registry_dir / "states" / "dataset_states.json",
                {
                    data_id: {
                        "data_type": "dataset",
                        "title": "State title",
                        "verification_flags": ["open"],
                    }
                },
            )

            entries = build_esa_cci_registry_entries(
                descriptors_dir=registry_dir / "descriptors" / "esa-cci",
                states={
                    "dataset": {
                        data_id: {
                            "data_type": "dataset",
                            "title": "State title",
                        }
                    }
                },
                registry_dir=registry_dir,
            )

            self.assertEqual(1, len(entries))
            entry = entries[0]
            self.assertEqual(data_id, entry["canonical_id"])
            self.assertEqual(
                "esacci.AEROSOL.day.L3.AAI.multi-sensor.multi-platform.MSAAI.r1",
                entry["collection_id"],
            )
            self.assertEqual("Descriptor title", entry["title"])
            self.assertEqual("AEROSOL", entry["ecv"])
            self.assertEqual("1.7", entry["version"])
            self.assertEqual([-10.0, -20.0, 30.0, 40.0], entry["bbox"])
            self.assertEqual(
                ["2001-01-01", "2020-12-31"], entry["time_range"]
            )
            self.assertEqual(
                "https://catalogue.ceda.ac.uk/uuid/test-uuid",
                entry["catalog_url"],
            )
            representation = entry["representations"][0]
            self.assertEqual("esa-cci", representation["store_id"])
            self.assertEqual(data_id, representation["data_id"])
            self.assertEqual("dataset", representation["data_type"])
            self.assertEqual(
                f"descriptors/esa-cci/{descriptor_path.name}",
                representation["descriptor_ref"],
            )
            self.assertTrue(representation["descriptor_hash"].startswith("sha256:"))

    def test_build_registry_writes_registry_json(self):
        with TemporaryDirectory() as tmp_dir:
            registry_dir = Path(tmp_dir)
            data_id = "esacci.TEST.mon.L3.PRODUCT.sensor.platform.MERGED.1-0.r1"
            _write_json(
                registry_dir
                / "descriptors"
                / "esa-cci"
                / safe_descriptor_file_name(data_id),
                {
                    "data_id": data_id,
                    "data_type": "dataset",
                    "attrs": {
                        "product_version": "1.0",
                        "uuid": "test-uuid",
                    },
                },
            )

            summary = build_esa_cci_registry(registry_dir=registry_dir)

            self.assertEqual(1, summary.entries)
            registry = json.loads((registry_dir / "registry.json").read_text())
            self.assertEqual(1, registry["schema_version"])
            self.assertIn("generated_at", registry)
            self.assertEqual(data_id, registry["datasets"][0]["canonical_id"])
            self.assertEqual(
                "https://catalogue.ceda.ac.uk/uuid/test-uuid",
                registry["datasets"][0]["catalog_url"],
            )

    def test_build_registry_allows_missing_catalog_url(self):
        with TemporaryDirectory() as tmp_dir:
            registry_dir = Path(tmp_dir)
            data_id = "esacci.TEST.mon.L3.PRODUCT.sensor.platform.MERGED.1-0.r1"
            _write_json(
                registry_dir
                / "descriptors"
                / "esa-cci"
                / safe_descriptor_file_name(data_id),
                {"data_id": data_id, "data_type": "dataset"},
            )

            build_esa_cci_registry(registry_dir=registry_dir)

            registry = json.loads((registry_dir / "registry.json").read_text())
            self.assertNotIn("catalog_url", registry["datasets"][0])

    def test_build_registry_uses_catalog_url_lookup(self):
        with TemporaryDirectory() as tmp_dir:
            registry_dir = Path(tmp_dir)
            data_id = "esacci.TEST.mon.L3.PRODUCT.sensor.platform.MERGED.1-0.r1"
            _write_json(
                registry_dir
                / "descriptors"
                / "esa-cci"
                / safe_descriptor_file_name(data_id),
                {"data_id": data_id, "data_type": "dataset"},
            )
            lookup_path = registry_dir / "catalog_urls.json"
            _write_json(lookup_path, {data_id: "https://example.com/catalog"})

            build_esa_cci_registry(
                registry_dir=registry_dir,
                catalog_urls_path=lookup_path,
            )

            registry = json.loads((registry_dir / "registry.json").read_text())
            self.assertEqual(
                "https://example.com/catalog",
                registry["datasets"][0]["catalog_url"],
            )

    def test_read_catalog_urls_ignores_empty_values(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "catalog_urls.json"
            _write_json(path, {"filled": "https://example.com", "empty": ""})

            urls = read_catalog_urls(path)

            self.assertEqual({"filled": "https://example.com"}, urls)

    def test_add_kerchunk_to_registry_uses_only_existing_descriptors(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            odp_data_id = "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.1-0.r1"
            kerchunk_data_id = "ESACCI-TEST-NAME-1-0"
            _write_json(
                root / "registry.json",
                {
                    "schema_version": 1,
                    "datasets": [
                        {
                            "canonical_id": odp_data_id,
                            "collection_id": derive_collection_id(odp_data_id),
                            "bbox": [-180.0, -90.0, 180.0, 90.0],
                            "time_range": ["2000-01-01", "2020-12-31"],
                            "representations": [],
                        }
                    ],
                },
            )
            _write_json(
                root / "refs.json",
                {
                    "references": [
                        {
                            "data_id": kerchunk_data_id,
                            "odp_data_id": odp_data_id,
                            "data_type": "dataset",
                            "reference_path": "https://example.com/ref.json",
                        },
                        {
                            "data_id": "missing-descriptor",
                            "odp_data_id": odp_data_id,
                            "data_type": "dataset",
                            "reference_path": "https://example.com/missing.json",
                        },
                    ]
                },
            )
            _write_json(
                root
                / "work"
                / safe_descriptor_file_name(kerchunk_data_id),
                {
                    "data_id": kerchunk_data_id,
                    "data_type": "dataset",
                    "bbox": [-10.0, -20.0, 30.0, 40.0],
                    "time_range": ["2000-01-01", "2019-12-31"],
                },
            )

            summary = add_kerchunk_to_registry(
                registry_dir=root,
                references_path=root / "refs.json",
                descriptors_dir=root / "work",
            )

            registry = json.loads((root / "registry.json").read_text())
            representation = registry["datasets"][0]["representations"][0]
            self.assertEqual(1, summary.representations)
            self.assertEqual(1, summary.skipped)
            self.assertIn("missing-descriptor", summary.skipped_details[0])
            self.assertIn("missing descriptor", summary.skipped_details[0])
            self.assertEqual("esa-cci-kc", representation["store_id"])
            self.assertEqual(kerchunk_data_id, representation["data_id"])
            self.assertEqual(
                "https://example.com/ref.json",
                representation["reference_path"],
            )
            self.assertEqual([-10.0, -20.0, 30.0, 40.0], representation["bbox"])
            self.assertEqual(
                ["2000-01-01", "2019-12-31"],
                representation["time_range"],
            )
            descriptor_path = (
                root
                / "descriptors"
                / "esa-cci-kc"
                / safe_descriptor_file_name(kerchunk_data_id)
            )
            self.assertTrue(descriptor_path.is_file())

    def test_derive_collection_id_keeps_non_version_suffix(self):
        self.assertEqual(
            "esacci.SST.day.L3C.SSTskin.AATSR.Envisat.AATSR.day",
            derive_collection_id(
                "esacci.SST.day.L3C.SSTskin.AATSR.Envisat.AATSR.2-1.day"
            ),
        )
        self.assertEqual(
            "esacci.FIRE.mon.L4.BA.multi-sensor.multi-platform.mr_har.grid",
            derive_collection_id(
                "esacci.FIRE.mon.L4.BA.multi-sensor.multi-platform.mr_har.v6-0-0.grid"
            ),
        )
        self.assertEqual(
            "esacci.AEROSOL.day.L3.AAI.multi-sensor.multi-platform.MSAAI.r1",
            derive_collection_id(
                "esacci.AEROSOL.day.L3.AAI.multi-sensor.multi-platform.MSAAI.1-7.r1"
            ),
        )

    def test_parse_version_sort_key_handles_prefixes_and_suffixes(self):
        self.assertLess(
            parse_version_sort_key("1-2"),
            parse_version_sort_key("ch4_v1-3"),
        )
        self.assertLess(
            parse_version_sort_key("v2-2a"),
            parse_version_sort_key("v2-2b"),
        )
        self.assertLess(
            parse_version_sort_key("v2-2b"),
            parse_version_sort_key("v2-2c"),
        )
        self.assertLess(
            parse_version_sort_key("v2-2c"),
            parse_version_sort_key("v2-3-8"),
        )
        self.assertGreater(
            parse_version_sort_key("fv0002"),
            parse_version_sort_key("fv0100"),
        )
        self.assertLess(
            parse_version_sort_key("4-0-1"),
            parse_version_sort_key("4-0-1r"),
        )
        self.assertLess(
            parse_version_sort_key("04-01"),
            parse_version_sort_key("04-01_seg-"),
        )

    def test_normalize_version_uses_public_dotted_format(self):
        cases = {
            "1-0": "1.0",
            "v2-2c": "2.2c",
            "4-0-1r": "4.0.1r",
            "ch4_v1-2": "1.2",
            "04-01_seg-": "4.1seg",
            "fv0002": "2.0",
            "v0001": "1.0",
            "fv0100": "1.0",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(expected, normalize_version(source))

    def test_add_supersession_links_rejects_duplicate_normalized_versions(self):
        collection_id = "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.r1"
        entries = [
            {
                "canonical_id": (
                    "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.01-00.r1"
                ),
                "collection_id": collection_id,
                "representations": [],
            },
            {
                "canonical_id": (
                    "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v1-0.r1"
                ),
                "collection_id": collection_id,
                "representations": [],
            },
        ]

        with self.assertRaisesRegex(ValueError, "Duplicate normalized versions"):
            add_supersession_links(entries)

    def test_add_supersession_links_connects_same_collection_versions(self):
        entries = [
            {
                "canonical_id": "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2b.r1",
                "collection_id": "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.r1",
                "representations": [],
            },
            {
                "canonical_id": "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2a.r1",
                "collection_id": "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.r1",
                "representations": [],
            },
            {
                "canonical_id": "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-3-8.r1",
                "collection_id": "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.r1",
                "representations": [],
            },
        ]

        linked = add_supersession_links(entries)
        by_id = {entry["canonical_id"]: entry for entry in linked}

        self.assertEqual(
            "2.2a",
            by_id[
                "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2a.r1"
            ]["version"],
        )
        self.assertEqual(
            "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2b.r1",
            by_id[
                "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2a.r1"
            ]["superseded_by"],
        )
        self.assertEqual(
            ["esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2a.r1"],
            by_id[
                "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2b.r1"
            ]["supersedes"],
        )
        self.assertEqual(
            "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-3-8.r1",
            by_id[
                "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2b.r1"
            ]["superseded_by"],
        )
        self.assertEqual(
            ["esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-2b.r1"],
            by_id[
                "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.v2-3-8.r1"
            ]["supersedes"],
        )
