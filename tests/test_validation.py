import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.constants import STATE_FILE_NAMES
from xcube_cci_metadata_builder.validation import validate_registry_artifacts


class ValidationTest(TestCase):
    def test_validation_accepts_consistent_artifacts(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            descriptor = root / "descriptors" / "esa-cci" / "id.json"
            _write_json(descriptor, {"data_id": "id"})
            _write_minimal_artifacts(root, descriptor)

            summary = validate_registry_artifacts(root)

            self.assertEqual(1, summary.datasets)
            self.assertEqual(1, summary.representations)
            self.assertEqual(1, summary.descriptors)

    def test_validation_rejects_descriptor_hash_mismatch(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            descriptor = root / "descriptors" / "esa-cci" / "id.json"
            _write_json(descriptor, {"data_id": "id"})
            _write_minimal_artifacts(root, descriptor)
            registry = json.loads((root / "registry.json").read_text())
            registry["datasets"][0]["representations"][0]["descriptor_hash"] = (
                "sha256:wrong"
            )
            _write_json(root / "registry.json", registry)

            with self.assertRaisesRegex(ValueError, "Descriptor hash mismatch"):
                validate_registry_artifacts(root)


def _write_minimal_artifacts(root: Path, descriptor: Path) -> None:
    descriptor_hash = hashlib.sha256(descriptor.read_bytes()).hexdigest()
    _write_json(
        root / "registry.json",
        {
            "schema_version": 1,
            "datasets": [
                {
                    "canonical_id": "id",
                    "collection_id": "id",
                    "representations": [
                        {
                            "store_id": "esa-cci",
                            "data_id": "id",
                            "descriptor_ref": descriptor.relative_to(root).as_posix(),
                            "descriptor_hash": f"sha256:{descriptor_hash}",
                        }
                    ],
                }
            ],
        },
    )
    _write_json(root / "build_info.json", {})
    _write_json(root / "schemas" / "registry.schema.json", {})
    _write_json(root / "schemas" / "build_info.schema.json", {})
    _write_json(
        root / "schemas" / "state-entry.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/state-entry.schema.json",
        },
    )
    _write_json(root / "schemas" / "states.schema.json", {})
    for file_name in STATE_FILE_NAMES.values():
        _write_json(root / "states" / file_name, {})


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
