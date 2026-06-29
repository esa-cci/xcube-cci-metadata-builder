"""Crash-resilient storage for per-data-ID builder results."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .constants import DATA_TYPES
from .jsonio import read_json, write_json

_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_result_file_name(data_id: str) -> str:
    """Return a stable, readable JSON filename for *data_id*."""

    readable = _SAFE_NAME_PATTERN.sub("_", data_id).strip("._")
    if not readable:
        readable = "data_id"
    digest = hashlib.sha1(data_id.encode("utf-8")).hexdigest()[:12]
    return f"{readable[:160]}--{digest}.json"


@dataclass(frozen=True)
class BuilderResult:
    """Persisted result for a single data ID."""

    data_id: str
    data_type: str
    status: str
    state_entry: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "data_id": self.data_id,
            "data_type": self.data_type,
            "status": self.status,
        }
        if self.state_entry is not None:
            value["state_entry"] = self.state_entry
        if self.error is not None:
            value["error"] = self.error
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BuilderResult":
        return cls(
            data_id=value["data_id"],
            data_type=value["data_type"],
            status=value["status"],
            state_entry=value.get("state_entry"),
            error=value.get("error"),
        )


class ResultStore:
    """Store one JSON result file per data ID and data type."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, data_type: str, data_id: str) -> Path:
        self._validate_data_type(data_type)
        return self.root / data_type / safe_result_file_name(data_id)

    def has_result(self, data_type: str, data_id: str) -> bool:
        return self.path_for(data_type, data_id).is_file()

    def write_result(self, result: BuilderResult) -> Path:
        path = self.path_for(result.data_type, result.data_id)
        write_json(path, result.to_dict())
        return path

    def iter_results(self, data_type: str | None = None) -> Iterator[BuilderResult]:
        data_types = (data_type,) if data_type else DATA_TYPES
        for item_type in data_types:
            self._validate_data_type(item_type)
            result_dir = self.root / item_type
            if not result_dir.is_dir():
                continue
            for path in sorted(result_dir.glob("*.json")):
                yield BuilderResult.from_dict(read_json(path))

    @staticmethod
    def _validate_data_type(data_type: str) -> None:
        if data_type not in DATA_TYPES:
            raise ValueError(f"Unsupported data type: {data_type!r}")
