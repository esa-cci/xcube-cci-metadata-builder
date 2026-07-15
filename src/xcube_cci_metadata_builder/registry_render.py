"""Render and validate a complete registry snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .build_info import build_info
from .jsonio import read_json, write_json
from .registry_build import (
    add_kerchunk_to_registry,
    add_zarr_to_registry,
    build_esa_cci_registry,
)
from .validation import ValidationSummary, validate_registry_artifacts


@dataclass(frozen=True)
class RegistryRenderSummary:
    """Summary of a complete registry render."""

    datasets: int
    kerchunk_representations: int
    zarr_representations: int
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
) -> RegistryRenderSummary:
    """Render all store representations from their current source artifacts."""

    root = Path(registry_dir)
    generated_at = _timestamp()
    registry_summary = build_esa_cci_registry(
        registry_dir=root,
        store_id=store_id,
        catalog_urls_path=catalog_urls_path,
        generated_at=generated_at,
    )
    kerchunk_summary = add_kerchunk_to_registry(
        registry_dir=root,
        references_path=kerchunk_references_path,
        descriptors_dir=kerchunk_descriptors_dir,
    )
    if kerchunk_summary.skipped:
        raise ValueError(
            f"Kerchunk integration skipped {kerchunk_summary.skipped} reference(s)"
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
    build_summary = build_info(root, generated_at=generated_at)
    validation = validate_registry_artifacts(root)
    return RegistryRenderSummary(
        datasets=validation.datasets,
        kerchunk_representations=kerchunk_summary.representations,
        zarr_representations=zarr_summary.processed,
        validation=validation,
        registry_path=registry_summary.output_path,
        build_info_path=build_summary.output_path,
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
