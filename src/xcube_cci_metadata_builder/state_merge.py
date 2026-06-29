"""Merge generated states with curated fields from previous states."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from .constants import MANUAL_STATE_FIELDS


def merge_manual_fields(
    generated_entry: Mapping[str, Any],
    previous_entry: Mapping[str, Any] | None,
    manual_fields: Iterable[str] = MANUAL_STATE_FIELDS,
) -> dict[str, Any]:
    """Copy curated fields from *previous_entry* into *generated_entry*."""

    merged = deepcopy(dict(generated_entry))
    if not previous_entry:
        return merged
    for field in manual_fields:
        if field in previous_entry:
            merged[field] = deepcopy(previous_entry[field])
    return merged


def merge_state_file(
    generated_states: Mapping[str, Mapping[str, Any]],
    previous_states: Mapping[str, Mapping[str, Any]] | None,
    manual_fields: Iterable[str] = MANUAL_STATE_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Merge a full state mapping and return it sorted by data ID."""

    previous_states = previous_states or {}
    merged = {
        data_id: merge_manual_fields(entry, previous_states.get(data_id), manual_fields)
        for data_id, entry in generated_states.items()
    }
    return dict(sorted(merged.items()))
