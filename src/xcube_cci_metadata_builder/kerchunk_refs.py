"""Collect Kerchunk reference metadata from ESA CCI ODP."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fsspec

from .constants import DATASET, GEODATAFRAME, VECTORDATACUBE
from .jsonio import write_json

LOG = logging.getLogger(__name__)
KERCHUNK_DATA_TYPES = (DATASET, VECTORDATACUBE, GEODATAFRAME)


@dataclass(frozen=True)
class KerchunkReferenceSummary:
    """Summary of collected Kerchunk reference metadata."""

    references: int
    output_path: Path


def collect_kerchunk_references(
    *,
    output_path: Path | str,
    data_types: Iterable[str] = KERCHUNK_DATA_TYPES,
    user_agent: str = "",
    limit: int | None = None,
) -> KerchunkReferenceSummary:
    """Collect Kerchunk references from ODP and persist them as JSON."""

    references = []
    seen: set[tuple[str, str]] = set()
    for data_type in data_types:
        entries = collect_kerchunk_references_for_type(
            data_type=data_type,
            user_agent=user_agent,
        )
        for entry in entries:
            key = (entry["odp_data_id"], entry["reference_path"])
            if key in seen:
                continue
            seen.add(key)
            references.append(entry)
            if limit is not None and len(references) >= limit:
                path = Path(output_path)
                write_json(path, {"references": references})
                return KerchunkReferenceSummary(
                    references=len(references),
                    output_path=path,
                )
    path = Path(output_path)
    write_json(path, {"references": references})
    return KerchunkReferenceSummary(references=len(references), output_path=path)


def collect_kerchunk_references_for_type(
    *,
    data_type: str,
    user_agent: str = "",
) -> list[dict[str, str]]:
    """Collect Kerchunk references for one xcube data type."""

    from xcube_cci.cciodp import CciOdp
    from xcube_cci.odpconnector import OdpConnector

    odp_connector = OdpConnector(user_agent)
    data_ids = odp_connector.get_drs_ids()
    cciodp = CciOdp(data_type=data_type, drs_ids=data_ids, user_agent=user_agent)
    return cciodp._session_executor.run_with_session(
        _collect_kerchunk_references_with_session,
        cciodp,
        data_type,
    )


async def _collect_kerchunk_references_with_session(
    session,
    cciodp,
    data_type: str,
) -> list[dict[str, str]]:
    from xcube_cci.cciodp import _extract_feature_info

    entries = []
    await cciodp._read_all_data_sources(session)
    for index, odp_data_id in enumerate(cciodp._drs_ids, start=1):
        LOG.info(
            "Collecting Kerchunk reference for %s data ID %s/%s: %s",
            data_type,
            index,
            len(cciodp._drs_ids),
            odp_data_id,
        )
        dataset_id = await cciodp._get_dataset_id(session, odp_data_id)
        data_source = cciodp._data_sources[odp_data_id]
        feature, _ = await cciodp._fetch_feature_and_num_nc_files_at(
            session,
            cciodp._opensearch_url,
            dict(
                parentIdentifier=dataset_id,
                startDate=data_source.get("temporal_coverage_start"),
                endDate=data_source.get("temporal_coverage_end"),
                drsId=odp_data_id,
            ),
            1,
        )
        if feature is None:
            continue
        feature_info = _extract_feature_info(feature)
        reference_path = feature_info[4].get("Kerchunk")
        if not reference_path:
            continue
        entries.append(
            {
                "data_id": ref_path_to_data_id(reference_path),
                "odp_data_id": odp_data_id,
                "data_type": data_type,
                "reference_path": reference_path,
            }
        )
    return entries


def ref_path_to_data_id(ref_path: str) -> str:
    """Return the reference file stem used as Kerchunk data ID."""

    protocol, path = fsspec.core.split_protocol(ref_path)
    if protocol in (None, "file", "local") and os.path.sep != "/":
        path = path.replace(os.path.sep, "/")
    name = path.rsplit("/", maxsplit=1)[-1]
    return name[:-5] if name.endswith(".json") else name
