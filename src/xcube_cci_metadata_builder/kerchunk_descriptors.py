"""Build Kerchunk descriptor artifacts from collected reference metadata."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import fsspec
import xarray as xr

from xcube.core.store.descriptor import new_data_descriptor

from .descriptors import (
    descriptor_to_dict,
    safe_descriptor_file_name,
    write_descriptor_file,
)
from .jsonio import read_json

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildKerchunkDescriptorsSummary:
    """Summary of Kerchunk descriptor generation."""

    described: int
    skipped: int
    errors: int


def build_kerchunk_descriptors(
    *,
    references_path: Path | str,
    descriptors_dir: Path | str,
    data_ids: Iterable[str] | None = None,
    name_pattern: str | None = None,
    limit: int | None = None,
    resume: bool = True,
) -> BuildKerchunkDescriptorsSummary:
    """Build Kerchunk descriptors from a collected reference JSON artifact."""

    requested_data_ids = set(data_ids) if data_ids is not None else None
    output_dir = Path(descriptors_dir)
    described = 0
    skipped = 0
    errors = 0

    references = list(
        _matching_references(
            references_path=references_path,
            data_ids=requested_data_ids,
            name_pattern=name_pattern,
        )
    )
    total = len(references)
    for index, reference in enumerate(references, start=1):
        if limit is not None and described >= limit:
            break

        data_id = reference["data_id"]
        reference_path = reference["reference_path"]
        descriptor_path = output_dir / safe_descriptor_file_name(data_id)
        if resume and descriptor_path.exists():
            skipped += 1
            continue

        LOG.info(
            "Building Kerchunk descriptor %s/%s: %s",
            index,
            total,
            data_id,
        )
        try:
            descriptor = describe_kerchunk_reference(
                data_id=data_id,
                reference_path=reference_path,
            )
            write_descriptor_file(
                output_dir,
                data_id,
                descriptor_to_dict(descriptor),
            )
            described += 1
        except Exception:
            LOG.exception("Failed building Kerchunk descriptor for %s", data_id)
            errors += 1

    skipped += _count_unmatched_references(
        references_path=references_path,
        data_ids=requested_data_ids,
        name_pattern=name_pattern,
    )
    return BuildKerchunkDescriptorsSummary(
        described=described,
        skipped=skipped,
        errors=errors,
    )


def describe_kerchunk_reference(*, data_id: str, reference_path: str):
    """Open a Kerchunk reference and return an xcube data descriptor."""

    ref_mapping = fsspec.get_mapper("reference://", fo=reference_path)
    dataset = xr.open_zarr(ref_mapping, consolidated=False)
    try:
        return new_data_descriptor(data_id, dataset)
    finally:
        dataset.close()


def _matching_references(
    *,
    references_path: Path | str,
    data_ids: set[str] | None,
    name_pattern: str | None,
) -> Iterator[dict[str, str]]:
    for reference in _read_references(references_path):
        data_id = reference["data_id"]
        if data_ids is not None and data_id not in data_ids:
            continue
        if not _data_id_matches_pattern(data_id, name_pattern):
            continue
        yield reference


def _count_unmatched_references(
    *,
    references_path: Path | str,
    data_ids: set[str] | None,
    name_pattern: str | None,
) -> int:
    count = 0
    for reference in _read_references(references_path):
        data_id = reference["data_id"]
        if data_ids is not None and data_id not in data_ids:
            count += 1
        elif not _data_id_matches_pattern(data_id, name_pattern):
            count += 1
    return count


def _read_references(references_path: Path | str) -> list[dict[str, str]]:
    payload = read_json(Path(references_path))
    references = payload.get("references")
    if not isinstance(references, list):
        raise ValueError(f"Kerchunk references file has no references list: {references_path}")
    return references


def _data_id_matches_pattern(data_id: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    return fnmatch.fnmatchcase(data_id, pattern) or fnmatch.fnmatchcase(
        data_id,
        f"*{pattern}*",
    )
