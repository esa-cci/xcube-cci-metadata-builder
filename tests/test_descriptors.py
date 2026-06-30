import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.descriptors import (
    descriptor_to_dict,
    safe_descriptor_file_name,
    write_descriptor_file,
)


class _DataType:
    alias = "dataset"


class _Mode(Enum):
    DEFAULT = "default"


class _Nested:
    def to_dict(self):
        return {"mode": _Mode.DEFAULT}


class _Descriptor:
    def to_dict(self):
        return {
            "data_type": _DataType(),
            "attrs": {
                "title": "Test",
                "created": datetime(2026, 6, 30, 12, 34, 56),
                "valid": date(2026, 6, 30),
            },
            "nested": _Nested(),
        }


class DescriptorsTest(TestCase):
    def test_descriptor_to_dict_returns_json_compatible_dict(self):
        descriptor = descriptor_to_dict(_Descriptor())

        self.assertEqual("dataset", descriptor["data_type"])
        self.assertEqual("Test", descriptor["attrs"]["title"])
        self.assertEqual("2026-06-30T12:34:56", descriptor["attrs"]["created"])
        self.assertEqual("2026-06-30", descriptor["attrs"]["valid"])
        self.assertEqual({"mode": "default"}, descriptor["nested"])

        json.dumps(descriptor)

    def test_safe_descriptor_file_name_is_stable_readable_and_json(self):
        data_id = "esacci.TEST/with unsafe chars"

        file_name = safe_descriptor_file_name(data_id)

        self.assertEqual(file_name, safe_descriptor_file_name(data_id))
        self.assertTrue(file_name.startswith("esacci.TEST_with_unsafe_chars--"))
        self.assertTrue(file_name.endswith(".json"))
        self.assertNotIn("/", file_name)

    def test_write_descriptor_file_writes_json(self):
        with TemporaryDirectory() as tmp_dir:
            descriptor = {"data_type": "dataset", "attrs": {"title": "Test"}}

            path = write_descriptor_file(Path(tmp_dir), "esacci.TEST", descriptor)

            self.assertTrue(path.is_file())
            self.assertEqual(
                descriptor,
                json.loads(path.read_text(encoding="utf-8")),
            )
