"""Run live xcube-cci state checks and persist per-data-ID results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from .state_checks import CheckConfig, check_data_id
from .constants import DATA_TYPES
from .result_store import ResultStore

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    checked: int
    skipped: int
    errors: int


def run_state_checks(
    *,
    store,
    result_store: ResultStore,
    data_types: Iterable[str] = DATA_TYPES,
    data_ids: Iterable[str] | None = None,
    resume: bool = True,
    limit: int | None = None,
    config: CheckConfig | None = None,
) -> RunSummary:
    """Run state checks and persist each result immediately."""

    checked = 0
    skipped = 0
    errors = 0
    config = config or CheckConfig()

    for data_type in data_types:
        ids_for_type = list(data_ids) if data_ids is not None else store.list_data_ids(data_type=data_type)
        total = len(ids_for_type)
        for index, data_id in enumerate(ids_for_type, start=1):
            if limit is not None and checked >= limit:
                return RunSummary(checked=checked, skipped=skipped, errors=errors)
            if resume and result_store.has_result(data_type, data_id):
                skipped += 1
                continue
            LOG.info(
                "Checking %s data ID %s/%s: %s",
                data_type,
                index,
                total,
                data_id,
            )
            result = check_data_id(store, data_id, data_type, config)
            result_store.write_result(result)
            checked += 1
            if result.status != "ok":
                errors += 1

    return RunSummary(checked=checked, skipped=skipped, errors=errors)
