"""Validation of rendered xcube-cci registry artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .constants import STATE_FILE_NAMES
from .jsonio import read_json


@dataclass(frozen=True)
class ValidationSummary:
    """Summary of successfully validated artifacts."""

    datasets: int
    representations: int
    states: int
    descriptors: int


def validate_registry_artifacts(registry_dir: Path | str) -> ValidationSummary:
    """Validate schemas, descriptor references, and descriptor hashes."""

    root = Path(registry_dir)
    registry = _validate_json(
        root / "registry.json", root / "schemas" / "registry.schema.json"
    )
    _validate_json(
        root / "build_info.json", root / "schemas" / "build_info.schema.json"
    )

    state_entry_schema = read_json(root / "schemas" / "state-entry.schema.json")
    schema_registry = Registry().with_resource(
        state_entry_schema["$id"], Resource.from_contents(state_entry_schema)
    )
    states = 0
    for file_name in STATE_FILE_NAMES.values():
        values = _validate_json(
            root / "states" / file_name,
            root / "schemas" / "states.schema.json",
            schema_registry=schema_registry,
        )
        states += len(values)

    representations = 0
    canonical_ids = [entry["canonical_id"] for entry in registry["datasets"]]
    if len(canonical_ids) != len(set(canonical_ids)):
        raise ValueError("Duplicate canonical_id in registry")
    for entry in registry["datasets"]:
        for representation in entry["representations"]:
            representations += 1
            descriptor_ref = representation.get("descriptor_ref")
            if not descriptor_ref:
                if (
                    representation.get("descriptor_omitted_reason") == "size_limit"
                    and representation.get("descriptor_size", 0) > 0
                    and "descriptor_hash" not in representation
                ):
                    continue
                raise ValueError(
                    "Missing descriptor_ref for "
                    f"{representation['store_id']}:{representation['data_id']}"
                )
            descriptor_path = root / descriptor_ref
            if not descriptor_path.is_file():
                raise ValueError(f"Missing descriptor: {descriptor_ref}")
            read_json(descriptor_path)
            expected_hash = representation.get("descriptor_hash")
            if not expected_hash:
                raise ValueError(f"Missing descriptor_hash: {descriptor_ref}")
            if expected_hash != _file_sha256(descriptor_path):
                raise ValueError(f"Descriptor hash mismatch: {descriptor_ref}")

    descriptor_paths = list((root / "descriptors").glob("*/*.json"))
    for descriptor_path in descriptor_paths:
        read_json(descriptor_path)

    return ValidationSummary(
        datasets=len(registry["datasets"]),
        representations=representations,
        states=states,
        descriptors=len(descriptor_paths),
    )


def _validate_json(
    path: Path,
    schema_path: Path,
    *,
    schema_registry: Registry | None = None,
):
    if not path.is_file():
        raise ValueError(f"Missing artifact: {path}")
    if not schema_path.is_file():
        raise ValueError(f"Missing schema: {schema_path}")
    value = read_json(path)
    schema = read_json(schema_path)
    validator = Draft202012Validator(schema, registry=schema_registry or Registry())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        location = "/".join(str(item) for item in errors[0].absolute_path)
        prefix = f" at {location}" if location else ""
        raise ValueError(f"Invalid {path.name}{prefix}: {errors[0].message}")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
