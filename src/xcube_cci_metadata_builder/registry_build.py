"""Build xcube-cci registry entries from rendered artifacts."""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import STATE_FILE_NAMES
from .descriptors import (
    descriptor_to_dict,
    safe_descriptor_file_name,
    write_descriptor_file,
)
from .jsonio import read_json, write_json

LOG = logging.getLogger(__name__)
_VERSION_PREFIX_PATTERN = re.compile(r"^(?:ch\d*_v|ch|fv|v)", re.IGNORECASE)
_VERSION_TOKEN_PATTERN = re.compile(r"\d+|[a-z]+", re.IGNORECASE)
_CEDA_CATALOGUE_UUID_URL = "https://catalogue.ceda.ac.uk/uuid/{uuid}"
_DEFAULT_CATALOG_URLS_PATH = Path(__file__).parent / "data" / "catalog_urls.json"


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


@dataclass(frozen=True)
class ZarrMapping:
    """Mapping from a Zarr data ID to its canonical ESA CCI ID."""

    data_id: str
    canonical_id: str


@dataclass(frozen=True)
class ZarrRegistrySummary:
    """Summary of a Zarr registry integration run."""

    processed: int
    described: int
    errors: int
    output_path: Path


def build_esa_cci_registry(
    *,
    registry_dir: Path | str,
    store_id: str = "esa-cci",
    schema_version: int = 1,
    catalog_urls_path: Path | str | None = None,
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
        catalog_urls=read_catalog_urls(catalog_urls_path),
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

        _set_registry_representation(
            entry=entry,
            descriptor=descriptor,
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


def add_zarr_to_registry(
    *,
    store,
    registry_dir: Path | str,
    mapping_path: Path | str,
    store_id: str = "esa-cci-zarr",
) -> ZarrRegistrySummary:
    """Build Zarr descriptors and add their representations to the registry."""

    root = Path(registry_dir)
    registry_path = root / "registry.json"
    registry = read_json(registry_path) if registry_path.is_file() else {}
    datasets = registry.setdefault("datasets", [])
    by_canonical_id = {
        entry["canonical_id"]: entry
        for entry in datasets
        if isinstance(entry, dict) and "canonical_id" in entry
    }
    descriptors_dir = root / "descriptors" / store_id
    processed = 0
    described = 0
    errors = 0

    for mapping in read_zarr_mappings(mapping_path):
        LOG.info("Adding Zarr data ID: %s", mapping.data_id)
        descriptor_path = descriptors_dir / safe_descriptor_file_name(mapping.data_id)
        try:
            if descriptor_path.is_file():
                descriptor = read_json(descriptor_path)
            else:
                data_descriptor = store.describe_data(
                    data_id=mapping.data_id,
                    data_type="dataset",
                )
                descriptor = descriptor_to_dict(data_descriptor)
                write_descriptor_file(
                    descriptors_dir,
                    mapping.data_id,
                    descriptor,
                )
                described += 1

            entry = by_canonical_id.get(mapping.canonical_id)
            if entry is None:
                entry = _new_registry_entry(mapping.canonical_id, descriptor)
                datasets.append(entry)
                by_canonical_id[mapping.canonical_id] = entry

            _set_registry_representation(
                entry=entry,
                descriptor=descriptor,
                store_id=store_id,
                data_id=mapping.data_id,
                data_type=str(descriptor.get("data_type") or "dataset"),
                descriptor_path=descriptor_path,
                registry_dir=root,
            )
            add_supersession_links(datasets)
            registry.setdefault("schema_version", 1)
            registry["generated_at"] = _timestamp()
            write_json(registry_path, registry)
            processed += 1
        except Exception:
            LOG.exception("Failed adding Zarr data ID: %s", mapping.data_id)
            errors += 1

    return ZarrRegistrySummary(
        processed=processed,
        described=described,
        errors=errors,
        output_path=registry_path,
    )


def read_zarr_mappings(mapping_path: Path | str) -> list[ZarrMapping]:
    """Read Zarr data IDs and canonical ESA CCI IDs from a CSV-like file."""

    mappings = []
    with Path(mapping_path).open("r", encoding="utf-8", newline="") as fp:
        for line_number, row in enumerate(csv.reader(fp, skipinitialspace=True), 1):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != 2 or not row[0].strip() or not row[1].strip():
                raise ValueError(
                    f"Invalid Zarr mapping at line {line_number}: {row!r}"
                )
            mappings.append(
                ZarrMapping(
                    data_id=row[0].strip(),
                    canonical_id=row[1].strip(),
                )
            )
    return mappings


def build_esa_cci_registry_entries(
    *,
    descriptors_dir: Path | str,
    states: dict[str, dict[str, Any]] | None = None,
    store_id: str = "esa-cci",
    registry_dir: Path | str | None = None,
    catalog_urls: dict[str, str] | None = None,
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
        catalog_url = _catalog_url(descriptor) or (catalog_urls or {}).get(data_id)
        if catalog_url:
            entry["catalog_url"] = catalog_url
        _set_coverage(entry, descriptor)
        entries.append(entry)
    return add_supersession_links(entries)


def read_catalog_urls(path: Path | str | None = None) -> dict[str, str]:
    """Read non-empty curated catalogue URLs keyed by canonical data ID."""

    lookup_path = Path(path) if path is not None else _DEFAULT_CATALOG_URLS_PATH
    if not lookup_path.is_file():
        return {}
    values = read_json(lookup_path)
    if not isinstance(values, dict):
        raise ValueError(f"Catalogue URL lookup must be an object: {lookup_path}")
    return {
        str(data_id): str(catalog_url)
        for data_id, catalog_url in values.items()
        if catalog_url
    }


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


def _catalog_url(descriptor: dict[str, Any]) -> str | None:
    attrs = descriptor.get("attrs") or {}
    catalog_url = attrs.get("catalog_url")
    if catalog_url:
        return str(catalog_url)
    uuid = attrs.get("uuid")
    if uuid:
        return _CEDA_CATALOGUE_UUID_URL.format(uuid=uuid)
    return None


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
    catalog_url = _catalog_url(descriptor)
    if catalog_url:
        entry["catalog_url"] = catalog_url
    _set_coverage(entry, descriptor)
    return entry


def _set_registry_representation(
    *,
    entry: dict[str, Any],
    descriptor: dict[str, Any],
    store_id: str,
    data_id: str,
    data_type: str,
    descriptor_path: Path,
    registry_dir: Path,
    reference_path: str | None = None,
) -> None:
    representation = {
        "store_id": store_id,
        "data_id": data_id,
        "data_type": data_type,
        "descriptor_ref": _descriptor_ref(descriptor_path, registry_dir),
        "descriptor_hash": _file_sha256(descriptor_path),
    }
    if reference_path is not None:
        representation["reference_path"] = reference_path
    _set_coverage_overrides(representation, entry, descriptor)
    representations = [
        item
        for item in entry.setdefault("representations", [])
        if not (item.get("store_id") == store_id and item.get("data_id") == data_id)
    ]
    representations.append(representation)
    entry["representations"] = representations


def _set_coverage(target: dict[str, Any], descriptor: dict[str, Any]) -> None:
    for field in ("bbox", "time_range"):
        value = descriptor.get(field)
        if value is not None:
            target[field] = value


def _set_coverage_overrides(
    representation: dict[str, Any],
    entry: dict[str, Any],
    descriptor: dict[str, Any],
) -> None:
    for field in ("bbox", "time_range"):
        value = descriptor.get(field)
        if value is not None and value != entry.get(field):
            representation[field] = value


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )
