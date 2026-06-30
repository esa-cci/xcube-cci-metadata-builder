"""Render xcube-cci state files from persisted builder results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import DATA_TYPES, STATE_FILE_NAMES
from .descriptors import write_descriptor_file
from .jsonio import read_json, write_json
from .result_store import ResultStore
from .state_merge import merge_state_file


def load_previous_states(previous_states_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Load previous xcube-cci state files keyed by data type."""

    root = Path(previous_states_dir)
    previous: dict[str, dict[str, Any]] = {}
    for data_type, file_name in STATE_FILE_NAMES.items():
        path = root / file_name
        previous[data_type] = read_json(path) if path.is_file() else {}
    return previous


def collect_generated_states(result_store: ResultStore) -> dict[str, dict[str, Any]]:
    """Collect state entries from per-data-ID result files."""

    generated = {data_type: {} for data_type in DATA_TYPES}
    for result in result_store.iter_results():
        if result.state_entry is not None:
            generated[result.data_type][result.data_id] = result.state_entry
            continue
        if result.status == "error":
            generated[result.data_type][result.data_id] = {
                "data_type": result.data_type,
                "verification_flags": [],
                "title": None,
            }
    return generated


def render_state_files(
    result_store: ResultStore,
    previous_states_dir: Path | str,
    output_dir: Path | str,
    descriptors_dir: Path | str | None = None,
) -> dict[str, Path]:
    """Render all xcube-cci state files from persisted builder results."""

    previous = load_previous_states(previous_states_dir)
    generated = collect_generated_states(result_store)
    output_root = Path(output_dir)
    written: dict[str, Path] = {}
    if descriptors_dir is not None:
        render_descriptor_files(result_store, descriptors_dir)
    for data_type, file_name in STATE_FILE_NAMES.items():
        states = merge_state_file(generated[data_type], previous.get(data_type))
        path = output_root / file_name
        write_json(path, states)
        written[data_type] = path
    return written


def render_descriptor_files(
    result_store: ResultStore,
    descriptors_dir: Path | str,
) -> dict[str, Path]:
    """Render descriptor files from persisted builder results."""

    written: dict[str, Path] = {}
    for result in result_store.iter_results():
        if result.descriptor is None:
            continue
        written[f"descriptor:{result.data_id}"] = write_descriptor_file(
            descriptors_dir,
            result.data_id,
            result.descriptor,
        )
    return written
