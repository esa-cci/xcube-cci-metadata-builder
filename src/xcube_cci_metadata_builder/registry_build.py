"""Build xcube-cci registry entries from rendered artifacts."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import STATE_FILE_NAMES
from .descriptors import safe_descriptor_file_name
from .jsonio import read_json, write_json

_VERSION_PREFIX_PATTERN = re.compile(r"^(?:ch\d*_v|ch|fv|v)", re.IGNORECASE)
_VERSION_TOKEN_PATTERN = re.compile(r"\d+|[a-z]+", re.IGNORECASE)


@dataclass(frozen=True)
class RegistryBuildSummary:
    """Summary of a registry build."""

    entries: int
    output_path: Path


@dataclass(frozen=True)
class KerchunkRegistrySummary:
    """Summary of Kerchunk registry integration."""

    representations: int
    descriptors: int
    skipped: int
    output_path: Path


def build_esa_cci_registry(
    *,
    registry_dir: Path | str,
    store_id: str = "esa-cci",
    schema_version: int = 1,
) -> RegistryBuildSummary:
    """Build ``registry.json`` entries for the ESA CCI ODP store."""

    root = Path(registry_dir)
    descriptors_dir = root / "descriptors" / store_id
    states = load_states(root / "states")
    datasets = build_esa_cci_registry_entries(
        descriptors_dir=descriptors_dir,
        states=states,
        store_id=store_id,
        registry_dir=root,
    )
    output_path = root / "registry.json"
    write_json(
        output_path,
        {
            "schema_version": schema_version,
            "generated_at": _timestamp(),
            "datasets": datasets,
        },
    )
    return RegistryBuildSummary(entries=len(datasets), output_path=output_path)


def add_kerchunk_to_registry(
    *,
    registry_dir: Path | str,
    references_path: Path | str,
    descriptors_dir: Path | str,
    store_id: str = "esa-cci-kc",
) -> KerchunkRegistrySummary:
    """Copy Kerchunk descriptors and add matching registry representations."""

    root = Path(registry_dir)
    registry_path = root / "registry.json"
    registry = read_json(registry_path) if registry_path.is_file() else {}
    datasets = registry.setdefault("datasets", [])
    by_canonical_id = {
        entry["canonical_id"]: entry
        for entry in datasets
        if isinstance(entry, dict) and "canonical_id" in entry
    }

    copied = 0
    representations = 0
    skipped = 0
    target_descriptors_dir = root / "descriptors" / store_id
    for reference in _read_kerchunk_references(references_path):
        data_id = reference.get("data_id")
        odp_data_id = reference.get("odp_data_id")
        reference_path = reference.get("reference_path")
        if not data_id or not odp_data_id or not reference_path:
            skipped += 1
            continue

        source_descriptor = Path(descriptors_dir) / safe_descriptor_file_name(data_id)
        if not source_descriptor.is_file():
            skipped += 1
            continue

        target_descriptor = target_descriptors_dir / source_descriptor.name
        target_descriptor.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_descriptor, target_descriptor)
        copied += 1

        descriptor = read_json(target_descriptor)
        entry = by_canonical_id.get(odp_data_id)
        if entry is None:
            entry = _new_registry_entry(odp_data_id, descriptor)
            datasets.append(entry)
            by_canonical_id[odp_data_id] = entry

        _set_kerchunk_representation(
            entry=entry,
            store_id=store_id,
            data_id=data_id,
            data_type=str(descriptor.get("data_type") or reference.get("data_type")),
            reference_path=str(reference_path),
            descriptor_path=target_descriptor,
            registry_dir=root,
        )
        representations += 1

    registry.setdefault("schema_version", 1)
    registry["generated_at"] = _timestamp()
    write_json(registry_path, registry)
    return KerchunkRegistrySummary(
        representations=representations,
        descriptors=copied,
        skipped=skipped,
        output_path=registry_path,
    )


def build_esa_cci_registry_entries(
    *,
    descriptors_dir: Path | str,
    states: dict[str, dict[str, Any]] | None = None,
    store_id: str = "esa-cci",
    registry_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Build registry entries for descriptor files in *descriptors_dir*."""

    root = Path(registry_dir) if registry_dir is not None else None
    descriptors_root = Path(descriptors_dir)
    states_by_id = _index_states_by_data_id(states or {})
    entries = []
    for descriptor_path in sorted(descriptors_root.glob("*.json")):
        descriptor = read_json(descriptor_path)
        data_id = descriptor.get("data_id")
        if not data_id:
            continue
        state_entry = states_by_id.get(data_id, {})
        attrs = descriptor.get("attrs") or {}
        data_type = _descriptor_data_type(descriptor, state_entry)
        descriptor_ref = _descriptor_ref(descriptor_path, root)
        representation = {
            "store_id": store_id,
            "data_id": data_id,
            "data_type": data_type,
            "descriptor_ref": descriptor_ref,
            "descriptor_hash": _file_sha256(descriptor_path),
        }
        entry = {
            "canonical_id": data_id,
            "collection_id": derive_collection_id(data_id),
            "representations": [representation],
        }
        title = _title(descriptor, state_entry)
        if title:
            entry["title"] = title
        ecv = attrs.get("ecv")
        if ecv:
            entry["ecv"] = str(ecv)
        version = attrs.get("product_version")
        if version:
            entry["version"] = str(version)
        entries.append(entry)
    return add_supersession_links(entries)


def add_supersession_links(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add supersession links between entries in the same collection."""

    by_collection: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        collection_id = entry["collection_id"]
        by_collection.setdefault(collection_id, []).append(entry)

    for collection_entries in by_collection.values():
        if len(collection_entries) < 2:
            continue
        sorted_entries = sorted(
            collection_entries,
            key=lambda entry: (
                parse_version_sort_key(_version_from_data_id(entry["canonical_id"])),
                entry["canonical_id"],
            ),
        )
        for older, newer in zip(sorted_entries, sorted_entries[1:]):
            older["superseded_by"] = newer["canonical_id"]
            newer["supersedes"] = [older["canonical_id"]]
    return entries


def load_states(states_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Load rendered state files keyed by data type."""

    root = Path(states_dir)
    states: dict[str, dict[str, Any]] = {}
    for data_type, file_name in STATE_FILE_NAMES.items():
        path = root / file_name
        states[data_type] = read_json(path) if path.is_file() else {}
    return states


def derive_collection_id(data_id: str) -> str:
    """Return a versionless collection identifier for an ESA CCI data ID."""

    parts = data_id.split(".")
    if len(parts) <= 8:
        return data_id
    return ".".join(parts[:8] + parts[9:])


def parse_version_sort_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """Return a sortable key for ESA CCI version strings."""

    normalized = version.strip().lower().strip("-_")
    normalized = _VERSION_PREFIX_PATTERN.sub("", normalized).strip("-_")
    normalized = normalized.replace("_seg", "-seg")
    if normalized.isdigit() and len(normalized) == 4:
        return ((0, int(normalized[:2])), (0, int(normalized[2:])))
    tokens = []
    for token in _VERSION_TOKEN_PATTERN.findall(normalized):
        if token.isdigit():
            tokens.append((0, int(token)))
        else:
            tokens.append((1, token))
    return tuple(tokens)


def _version_from_data_id(data_id: str) -> str:
    parts = data_id.split(".")
    if len(parts) <= 8:
        return ""
    return parts[8]


def _index_states_by_data_id(
    states: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for state_file in states.values():
        by_id.update(state_file)
    return by_id


def _descriptor_data_type(
    descriptor: dict[str, Any],
    state_entry: dict[str, Any],
) -> str | None:
    data_type = descriptor.get("data_type") or state_entry.get("data_type")
    return str(data_type) if data_type is not None else None


def _descriptor_ref(descriptor_path: Path, registry_dir: Path | None) -> str:
    if registry_dir is None:
        return descriptor_path.as_posix()
    return descriptor_path.relative_to(registry_dir).as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _title(descriptor: dict[str, Any], state_entry: dict[str, Any]) -> str | None:
    attrs = descriptor.get("attrs") or {}
    title = attrs.get("title") or state_entry.get("title")
    return str(title) if title else None


def _read_kerchunk_references(references_path: Path | str) -> list[dict[str, Any]]:
    payload = read_json(Path(references_path))
    references = payload.get("references")
    if not isinstance(references, list):
        raise ValueError(
            f"Kerchunk references file has no references list: {references_path}"
        )
    return references


def _new_registry_entry(
    canonical_id: str,
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "canonical_id": canonical_id,
        "collection_id": derive_collection_id(canonical_id),
        "representations": [],
    }
    attrs = descriptor.get("attrs") or {}
    title = attrs.get("title")
    if title:
        entry["title"] = str(title)
    ecv = attrs.get("ecv")
    if ecv:
        entry["ecv"] = str(ecv)
    version = attrs.get("product_version")
    if version:
        entry["version"] = str(version)
    return entry


def _set_kerchunk_representation(
    *,
    entry: dict[str, Any],
    store_id: str,
    data_id: str,
    data_type: str,
    reference_path: str,
    descriptor_path: Path,
    registry_dir: Path,
) -> None:
    representation = {
        "store_id": store_id,
        "data_id": data_id,
        "data_type": data_type,
        "reference_path": reference_path,
        "descriptor_ref": _descriptor_ref(descriptor_path, registry_dir),
        "descriptor_hash": _file_sha256(descriptor_path),
    }
    representations = [
        item
        for item in entry.setdefault("representations", [])
        if not (item.get("store_id") == store_id and item.get("data_id") == data_id)
    ]
    representations.append(representation)
    entry["representations"] = representations


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )
