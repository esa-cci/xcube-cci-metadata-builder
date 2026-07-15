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
