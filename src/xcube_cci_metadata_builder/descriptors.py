"""Descriptor serialization and rendering helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .jsonio import write_json

_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def descriptor_to_dict(descriptor: Any) -> dict[str, Any]:
    """Return a JSON-compatible dictionary for an xcube data descriptor."""

    if hasattr(descriptor, "to_dict"):
        value = descriptor.to_dict()
    elif hasattr(descriptor, "__dict__"):
        value = {
            key: item
            for key, item in vars(descriptor).items()
            if not key.startswith("_")
        }
    else:
        raise TypeError(f"Cannot serialize descriptor {descriptor!r}.")

    value = _to_json_compatible(value)
    if not isinstance(value, dict):
        raise TypeError(f"Descriptor serialized to non-dict value {value!r}.")
    return value


def safe_descriptor_file_name(data_id: str) -> str:
    """Return a stable descriptor filename for *data_id*."""

    readable = _SAFE_NAME_PATTERN.sub("_", data_id).strip("._") or "data_id"
    digest = hashlib.sha1(data_id.encode("utf-8")).hexdigest()[:12]
    return f"{readable[:160]}--{digest}.json"


def write_descriptor_file(
    descriptors_dir: Path | str,
    data_id: str,
    descriptor: dict[str, Any],
) -> Path:
    """Write one descriptor artifact and return its path."""

    path = Path(descriptors_dir) / safe_descriptor_file_name(data_id)
    write_json(path, descriptor)
    return path


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "alias"):
        return getattr(value, "alias")
    if hasattr(value, "to_dict"):
        return _to_json_compatible(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            key: _to_json_compatible(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)
