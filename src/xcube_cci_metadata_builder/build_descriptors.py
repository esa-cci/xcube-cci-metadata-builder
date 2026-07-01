"""Build descriptor artifacts directly from an xcube data store."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .constants import DATA_TYPES
from .descriptors import descriptor_to_dict, write_descriptor_file

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildDescriptorsSummary:
    described: int
    skipped: int
    errors: int


def build_descriptors(
    *,
    store,
    registry_dir: Path | str,
    store_id: str = "esa-cci",
    data_types: Iterable[str] = DATA_TYPES,
    name_pattern: str | None = None,
    data_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> BuildDescriptorsSummary:
    """Describe matching data IDs and write descriptor files to a registry."""

    described = 0
    skipped = 0
    errors = 0
    descriptors_dir = Path(registry_dir) / "descriptors" / store_id

    for data_type in data_types:
        ids_for_type = (
            list(data_ids)
            if data_ids is not None
            else store.list_data_ids(data_type=data_type)
        )
        matching_ids = [
            data_id
            for data_id in ids_for_type
            if data_id_matches_pattern(data_id, name_pattern)
        ]
        total = len(matching_ids)
        skipped = len(ids_for_type) - total
        for index, data_id in enumerate(matching_ids, start=1):
            if limit is not None and described >= limit:
                return BuildDescriptorsSummary(
                    described=described,
                    skipped=skipped,
                    errors=errors,
                )
            LOG.info(
                "Describing %s data ID %s/%s: %s",
                data_type,
                index,
                total,
                data_id,
            )
            try:
                descriptor = store.describe_data(data_id=data_id, data_type=data_type)
                write_descriptor_file(
                    descriptors_dir,
                    data_id,
                    descriptor_to_dict(descriptor),
                )
                described += 1
            except Exception:
                LOG.exception(
                    "Failed describing %s data ID: %s",
                    data_type,
                    data_id,
                )
                errors += 1

    return BuildDescriptorsSummary(described=described, skipped=skipped, errors=errors)


def data_id_matches_pattern(data_id: str, pattern: str | None) -> bool:
    """Return whether *data_id* matches a user supplied wildcard pattern."""

    if not pattern:
        return True
    return fnmatch.fnmatchcase(data_id, pattern) or fnmatch.fnmatchcase(
        data_id,
        f"*{pattern}*",
    )
