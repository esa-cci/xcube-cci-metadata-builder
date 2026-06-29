"""Small JSON helpers with atomic writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fp:
        json.dump(value, fp, indent=2, sort_keys=True)
        fp.write("\n")
    os.replace(tmp_path, path)
