"""Render and validate a complete registry snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

from .build_info import build_info
from .jsonio import read_json, write_json
from .registry_build import (
    add_kerchunk_to_registry,
    add_zarr_to_registry,
    build_esa_cci_registry,
)
from .validation import ValidationSummary, validate_registry_artifacts

DEFAULT_MAX_DESCRIPTOR_SIZE = 2 * 1024 * 1024


@dataclass(frozen=True)
class RegistryRenderSummary:
    """Summary of a complete registry render."""

    datasets: int
    kerchunk_representations: int
    kerchunk_skipped: int
    zarr_representations: int
    zarr_skipped: int
    oversized_descriptors: int
    validation: ValidationSummary
    registry_path: Path
    build_info_path: Path


def render_registry(
    registry_dir: Path | str,
    *,
    kerchunk_references_path: Path | str,
    kerchunk_descriptors_dir: Path | str,
    zarr_mapping_path: Path | str,
    store_id: str = "esa-cci",
    catalog_urls_path: Path | str | None = None,
    max_descriptor_size: int = DEFAULT_MAX_DESCRIPTOR_SIZE,
) -> RegistryRenderSummary:
    """Render all store representations and publish a complete valid snapshot."""

    root = Path(registry_dir)
    with TemporaryDirectory(prefix="cci-registry-render-") as tmp_dir:
        staged_root = Path(tmp_dir) / "registry"
        shutil.copytree(root, staged_root)
        summary = _render_registry_in_place(
            staged_root,
            kerchunk_references_path=kerchunk_references_path,
            kerchunk_descriptors_dir=kerchunk_descriptors_dir,
            zarr_mapping_path=zarr_mapping_path,
            store_id=store_id,
            catalog_urls_path=catalog_urls_path,
            max_descriptor_size=max_descriptor_size,
        )
        _publish_render(staged_root, root)

    return RegistryRenderSummary(
        datasets=summary.datasets,
        kerchunk_representations=summary.kerchunk_representations,
        kerchunk_skipped=summary.kerchunk_skipped,
        zarr_representations=summary.zarr_representations,
        zarr_skipped=summary.zarr_skipped,
        oversized_descriptors=summary.oversized_descriptors,
        validation=summary.validation,
        registry_path=root / "registry.json",
        build_info_path=root / "build_info.json",
    )


def _render_registry_in_place(
    root: Path,
    *,
    kerchunk_references_path: Path | str,
    kerchunk_descriptors_dir: Path | str,
    zarr_mapping_path: Path | str,
    store_id: str,
    catalog_urls_path: Path | str | None,
    max_descriptor_size: int,
) -> RegistryRenderSummary:
    generated_at = _timestamp()
    previous_registry = _read_registry(root)
    registry_summary = build_esa_cci_registry(
        registry_dir=root,
        store_id=store_id,
        catalog_urls_path=catalog_urls_path,
        generated_at=generated_at,
    )
    _restore_omitted_descriptor_representations(
        registry_summary.output_path,
        previous_registry,
    )
    kerchunk_summary = add_kerchunk_to_registry(
        registry_dir=root,
        references_path=kerchunk_references_path,
        descriptors_dir=kerchunk_descriptors_dir,
    )
    zarr_summary = add_zarr_to_registry(
        store=None,
        registry_dir=root,
        mapping_path=zarr_mapping_path,
    )
    if zarr_summary.errors:
        raise ValueError(
            f"Zarr integration failed for {zarr_summary.errors} mapping(s)"
        )
    registry = read_json(registry_summary.output_path)
    registry["generated_at"] = generated_at
    write_json(registry_summary.output_path, registry)
    oversized_descriptors = _omit_oversized_descriptors(
        root,
        max_descriptor_size=max_descriptor_size,
    )
    build_summary = build_info(root, generated_at=generated_at)
    validation = validate_registry_artifacts(root)
    return RegistryRenderSummary(
        datasets=validation.datasets,
        kerchunk_representations=kerchunk_summary.representations,
        kerchunk_skipped=kerchunk_summary.skipped,
        zarr_representations=zarr_summary.processed,
        zarr_skipped=zarr_summary.skipped,
        oversized_descriptors=oversized_descriptors,
        validation=validation,
        registry_path=registry_summary.output_path,
        build_info_path=build_summary.output_path,
    )


def _publish_render(staged_root: Path, target_root: Path) -> None:
    _replace_directory(
        staged_root / "descriptors",
        target_root / "descriptors",
    )
    for file_name in ("registry.json", "build_info.json"):
        _replace_file(staged_root / file_name, target_root / file_name)


def _replace_file(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)


def _replace_directory(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    backup = target.with_name(f".{target.name}.{uuid4().hex}.bak")
    shutil.copytree(source, temporary)
    had_target = target.exists()
    try:
        if had_target:
            target.replace(backup)
        temporary.replace(target)
    except BaseException:
        if had_target and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if backup.exists():
            shutil.rmtree(backup)


def _read_registry(root: Path) -> dict:
    path = root / "registry.json"
    return read_json(path) if path.is_file() else {}


def _restore_omitted_descriptor_representations(
    registry_path: Path,
    previous_registry: dict,
) -> None:
    registry = read_json(registry_path)
    entries_by_id = {
        entry["canonical_id"]: entry for entry in registry.get("datasets", [])
    }
    for previous_entry in previous_registry.get("datasets", []):
        omitted = [
            representation
            for representation in previous_entry.get("representations", [])
            if representation.get("descriptor_omitted_reason") == "size_limit"
        ]
        if not omitted:
            continue
        entry = entries_by_id.get(previous_entry["canonical_id"])
        if entry is None:
            entry = {
                key: value
                for key, value in previous_entry.items()
                if key != "representations"
            }
            entry["representations"] = []
            registry["datasets"].append(entry)
            entries_by_id[entry["canonical_id"]] = entry
        existing = {
            (representation["store_id"], representation["data_id"])
            for representation in entry["representations"]
        }
        entry["representations"].extend(
            representation
            for representation in omitted
            if (representation["store_id"], representation["data_id"]) not in existing
        )
    write_json(registry_path, registry)


def _omit_oversized_descriptors(
    root: Path,
    *,
    max_descriptor_size: int,
) -> int:
    registry_path = root / "registry.json"
    registry = read_json(registry_path)
    omitted = 0
    descriptor_sizes = {}
    paths_to_remove = set()
    for entry in registry["datasets"]:
        for representation in entry["representations"]:
            descriptor_ref = representation.get("descriptor_ref")
            if not descriptor_ref:
                continue
            descriptor_path = root / descriptor_ref
            descriptor_size = descriptor_sizes.setdefault(
                descriptor_ref,
                descriptor_path.stat().st_size,
            )
            if descriptor_size <= max_descriptor_size:
                continue
            representation.pop("descriptor_ref")
            representation.pop("descriptor_hash", None)
            representation["descriptor_omitted_reason"] = "size_limit"
            representation["descriptor_size"] = descriptor_size
            paths_to_remove.add(descriptor_path)
            omitted += 1
    for descriptor_path in paths_to_remove:
        descriptor_path.unlink()
    write_json(registry_path, registry)
    return omitted


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
