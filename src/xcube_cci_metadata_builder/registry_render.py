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


@dataclass(frozen=True)
class RegistryRenderSummary:
    """Summary of a complete registry render."""

    datasets: int
    kerchunk_representations: int
    kerchunk_skipped: int
    zarr_representations: int
    zarr_skipped: int
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
        )
        _publish_render(staged_root, root)

    return RegistryRenderSummary(
        datasets=summary.datasets,
        kerchunk_representations=summary.kerchunk_representations,
        kerchunk_skipped=summary.kerchunk_skipped,
        zarr_representations=summary.zarr_representations,
        zarr_skipped=summary.zarr_skipped,
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
) -> RegistryRenderSummary:
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
        kerchunk_skipped=kerchunk_summary.skipped,
        zarr_representations=zarr_summary.processed,
        zarr_skipped=zarr_summary.skipped,
        validation=validation,
        registry_path=registry_summary.output_path,
        build_info_path=build_summary.output_path,
    )


def _publish_render(staged_root: Path, target_root: Path) -> None:
    _replace_directory(
        staged_root / "descriptors" / "esa-cci-kc",
        target_root / "descriptors" / "esa-cci-kc",
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


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
