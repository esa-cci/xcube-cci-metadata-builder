"""Build provenance for a rendered xcube-cci registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .constants import STATE_FILE_NAMES
from .jsonio import read_json, write_json


@dataclass(frozen=True)
class BuildInfoSummary:
    """Summary of a build-info render."""

    output_path: Path
    counts: dict[str, int]


def build_info(
    registry_dir: Path | str,
    *,
    generated_at: str | None = None,
) -> BuildInfoSummary:
    """Write ``build_info.json`` for the artifacts in *registry_dir*."""

    root = Path(registry_dir)
    counts = _artifact_counts(root)
    output_path = root / "build_info.json"
    write_json(
        output_path,
        {
            "generated_at": generated_at or _timestamp(),
            "builder": {
                "name": "xcube-cci-metadata-builder",
                "version": _package_version("xcube-cci-metadata-builder"),
            },
            "xcube_cci": {"version": _package_version("xcube-cci")},
            "xcube": {"version": _package_version("xcube")},
            "source": {
                "normalize_data": True,
                "store_ids": _registry_store_ids(root),
            },
            "outputs": {
                "registry": "registry.json",
                "states": {
                    data_type: f"states/{file_name}"
                    for data_type, file_name in STATE_FILE_NAMES.items()
                },
                "descriptors": "descriptors/",
            },
            "counts": counts,
        },
    )
    return BuildInfoSummary(output_path=output_path, counts=counts)


def _artifact_counts(root: Path) -> dict[str, int]:
    registry_path = root / "registry.json"
    registry = read_json(registry_path) if registry_path.is_file() else {}
    datasets = registry.get("datasets") or []
    counts = {
        "registry_datasets": len(datasets),
        "registry_representations": sum(
            len(entry.get("representations") or []) for entry in datasets
        ),
        "descriptors": len(list((root / "descriptors").glob("*/*.json"))),
    }
    for data_type, file_name in STATE_FILE_NAMES.items():
        path = root / "states" / file_name
        values = read_json(path) if path.is_file() else {}
        counts[f"states_{data_type}"] = len(values)
    return counts


def _registry_store_ids(root: Path) -> list[str]:
    path = root / "registry.json"
    registry = read_json(path) if path.is_file() else {}
    return sorted(
        {
            representation["store_id"]
            for entry in registry.get("datasets") or []
            for representation in entry.get("representations") or []
            if representation.get("store_id")
        }
    )


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
