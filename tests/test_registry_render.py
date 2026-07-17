import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.constants import STATE_FILE_NAMES
from xcube_cci_metadata_builder.descriptors import safe_descriptor_file_name
from xcube_cci_metadata_builder.registry_render import render_registry


class RegistryRenderTest(TestCase):
    def test_render_uses_current_sources_not_previous_registry(self):
        """Regression: a full render must not restore previous representations."""

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            canonical_id = "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.1-0.r1"
            _write_json(
                root / "registry.json",
                {
                    "datasets": [
                        {
                            "canonical_id": "obsolete",
                            "representations": [{"store_id": "obsolete-store"}],
                        }
                    ]
                },
            )
            _write_descriptor(root / "descriptors" / "esa-cci", canonical_id)
            _write_descriptor(root / "work" / "kc", "kerchunk-id")
            _write_descriptor(
                root / "descriptors" / "esa-cci-zarr", "zarr-id"
            )
            references_path = root / "work" / "refs.json"
            _write_json(
                references_path,
                {
                    "references": [
                        {
                            "data_id": "kerchunk-id",
                            "odp_data_id": canonical_id,
                            "data_type": "dataset",
                            "reference_path": "https://example.com/ref.json",
                        }
                    ]
                },
            )
            mapping_path = root / "zarr-mapping"
            mapping_path.write_text(f"zarr-id, {canonical_id}\n", encoding="utf-8")
            _write_validation_inputs(root)

            summary = render_registry(
                root,
                kerchunk_references_path=references_path,
                kerchunk_descriptors_dir=root / "work" / "kc",
                zarr_mapping_path=mapping_path,
            )

            registry = json.loads((root / "registry.json").read_text())
            store_ids = {
                representation["store_id"]
                for representation in registry["datasets"][0]["representations"]
            }
            self.assertEqual(1, summary.datasets)
            self.assertEqual(
                {"esa-cci", "esa-cci-kc", "esa-cci-zarr"}, store_ids
            )

    def test_oversized_descriptor_is_omitted_and_entry_survives_rerender(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            data_id = "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.1-0.r1"
            descriptor_path = (
                root
                / "descriptors"
                / "esa-cci"
                / safe_descriptor_file_name(data_id)
            )
            _write_json(
                descriptor_path,
                {
                    "data_id": data_id,
                    "data_type": "dataset",
                    "attrs": {"padding": "x" * 200},
                },
            )
            references_path = root / "refs.json"
            mapping_path = root / "zarr-mapping"
            _write_json(references_path, {"references": []})
            mapping_path.write_text("", encoding="utf-8")
            _write_validation_inputs(root)

            first = render_registry(
                root,
                kerchunk_references_path=references_path,
                kerchunk_descriptors_dir=root / "kc",
                zarr_mapping_path=mapping_path,
                max_descriptor_size=100,
            )
            second = render_registry(
                root,
                kerchunk_references_path=references_path,
                kerchunk_descriptors_dir=root / "kc",
                zarr_mapping_path=mapping_path,
                max_descriptor_size=100,
            )

            representation = json.loads(
                (root / "registry.json").read_text()
            )["datasets"][0]["representations"][0]
            self.assertEqual(1, first.oversized_descriptors)
            self.assertEqual(0, second.oversized_descriptors)
            self.assertFalse(descriptor_path.exists())
            self.assertNotIn("descriptor_ref", representation)
            self.assertEqual(
                "size_limit",
                representation["descriptor_omitted_reason"],
            )

    def test_failed_render_does_not_modify_registry(self):
        """Regression: a later render failure must not publish earlier changes."""

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            old_registry = {"datasets": [{"canonical_id": "existing-zarr-entry"}]}
            old_build_info = {"generated_at": "previous-build"}
            _write_json(root / "registry.json", old_registry)
            _write_json(root / "build_info.json", old_build_info)
            _write_descriptor(
                root / "descriptors" / "esa-cci",
                "esacci.TEST.mon.L3.PROD.sensor.platform.NAME.1-0.r1",
            )
            _write_descriptor(root / "work" / "kc", "kerchunk-id")
            references_path = root / "work" / "refs.json"
            _write_json(
                references_path,
                {
                    "references": [
                        {
                            "data_id": "kerchunk-id",
                            "odp_data_id": "odp-id",
                            "reference_path": "https://example.com/ref.json",
                        }
                    ]
                },
            )

            with self.assertRaises(FileNotFoundError):
                render_registry(
                    root,
                    kerchunk_references_path=references_path,
                    kerchunk_descriptors_dir=root / "work" / "kc",
                    zarr_mapping_path=root / "unused-zarr-mapping",
                )

            self.assertEqual(old_registry, json.loads((root / "registry.json").read_text()))
            self.assertEqual(
                old_build_info,
                json.loads((root / "build_info.json").read_text()),
            )
            self.assertFalse(
                (
                    root
                    / "descriptors"
                    / "esa-cci-kc"
                    / safe_descriptor_file_name("kerchunk-id")
                ).exists()
            )


def _write_descriptor(directory: Path, data_id: str) -> None:
    _write_json(
        directory / safe_descriptor_file_name(data_id),
        {"data_id": data_id, "data_type": "dataset"},
    )


def _write_validation_inputs(root: Path) -> None:
    for name in ("registry.schema.json", "build_info.schema.json", "states.schema.json"):
        _write_json(root / "schemas" / name, {})
    _write_json(
        root / "schemas" / "state-entry.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/state-entry.schema.json",
        },
    )
    for file_name in STATE_FILE_NAMES.values():
        _write_json(root / "states" / file_name, {})


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
