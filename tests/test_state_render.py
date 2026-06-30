import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xcube_cci_metadata_builder.result_store import BuilderResult, ResultStore
from xcube_cci_metadata_builder.state_render import render_state_files


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class StateRenderTest(TestCase):
    def test_render_state_files_merges_previous_manual_fields(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            previous_dir = tmp_path / "previous"
            output_dir = tmp_path / "out"
            results = ResultStore(tmp_path / "results")
            data_id = "esacci.TEST"
            _write_json(
                previous_dir / "dataset_states.json",
                {
                    data_id: {
                        "data_type": "dataset",
                        "verification_flags": ["open"],
                        "title": "Old",
                        "var_names": ["old_var"],
                    }
                },
            )
            results.write_result(
                BuilderResult(
                    data_id=data_id,
                    data_type="dataset",
                    status="ok",
                    state_entry={
                        "data_type": "dataset",
                        "verification_flags": ["open", "constrain_time"],
                        "title": "New",
                    },
                )
            )

            render_state_files(results, previous_dir, output_dir)

            rendered = json.loads((output_dir / "dataset_states.json").read_text())
            self.assertEqual("New", rendered[data_id]["title"])
            self.assertEqual(["old_var"], rendered[data_id]["var_names"])
            self.assertTrue((output_dir / "datatree_states.json").is_file())
            self.assertTrue((output_dir / "geodataframe_states.json").is_file())
            self.assertTrue((output_dir / "vectordatacube_states.json").is_file())

    def test_render_state_files_uses_previous_title_when_generated_title_is_missing(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            previous_dir = tmp_path / "previous"
            output_dir = tmp_path / "out"
            results = ResultStore(tmp_path / "results")
            data_id = "esacci.TEST"
            _write_json(
                previous_dir / "dataset_states.json",
                {
                    data_id: {
                        "data_type": "dataset",
                        "verification_flags": ["open"],
                        "title": "Previous title",
                    }
                },
            )
            results.write_result(
                BuilderResult(
                    data_id=data_id,
                    data_type="dataset",
                    status="ok",
                    state_entry={
                        "data_type": "dataset",
                        "verification_flags": ["open"],
                        "title": None,
                    },
                )
            )

            render_state_files(results, previous_dir, output_dir)

            rendered = json.loads((output_dir / "dataset_states.json").read_text())
            self.assertEqual("Previous title", rendered[data_id]["title"])

    def test_render_state_files_merges_error_result_as_empty_verification_flags(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            previous_dir = tmp_path / "previous"
            output_dir = tmp_path / "out"
            results = ResultStore(tmp_path / "results")
            data_id = "esacci.TEST"
            _write_json(
                previous_dir / "dataset_states.json",
                {
                    data_id: {
                        "data_type": "dataset",
                        "verification_flags": ["open", "write_zarr"],
                        "title": "Previous title",
                        "var_names": ["a"],
                    }
                },
            )
            results.write_result(
                BuilderResult(
                    data_id=data_id,
                    data_type="dataset",
                    status="error",
                    error={"type": "RuntimeError", "message": "broken"},
                )
            )

            render_state_files(results, previous_dir, output_dir)

            rendered = json.loads((output_dir / "dataset_states.json").read_text())
            self.assertEqual([], rendered[data_id]["verification_flags"])
            self.assertEqual("Previous title", rendered[data_id]["title"])
            self.assertEqual(["a"], rendered[data_id]["var_names"])

    def test_render_state_files_preserves_error_result_state_entry(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            previous_dir = tmp_path / "previous"
            output_dir = tmp_path / "out"
            results = ResultStore(tmp_path / "results")
            data_id = "esacci.TEST"
            _write_json(
                previous_dir / "dataset_states.json",
                {
                    data_id: {
                        "data_type": "dataset",
                        "verification_flags": ["open", "write_zarr"],
                        "title": "Previous title",
                    }
                },
            )
            results.write_result(
                BuilderResult(
                    data_id=data_id,
                    data_type="dataset",
                    status="error",
                    state_entry={
                        "data_type": "dataset",
                        "verification_flags": ["open"],
                        "title": None,
                    },
                    error={"type": "RuntimeError", "message": "write failed"},
                )
            )

            render_state_files(results, previous_dir, output_dir)

            rendered = json.loads((output_dir / "dataset_states.json").read_text())
            self.assertEqual(["open"], rendered[data_id]["verification_flags"])
            self.assertEqual("Previous title", rendered[data_id]["title"])

    def test_render_state_files_can_write_descriptors_from_results(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            previous_dir = tmp_path / "previous"
            output_dir = tmp_path / "out"
            descriptors_dir = tmp_path / "descriptors"
            results = ResultStore(tmp_path / "results")
            data_id = "esacci.TEST"
            descriptor = {
                "data_type": "dataset",
                "attrs": {"title": "Descriptor title"},
            }
            results.write_result(
                BuilderResult(
                    data_id=data_id,
                    data_type="dataset",
                    status="ok",
                    state_entry={
                        "data_type": "dataset",
                        "verification_flags": ["open"],
                        "title": "Descriptor title",
                    },
                    descriptor=descriptor,
                )
            )

            render_state_files(
                results,
                previous_dir,
                output_dir,
                descriptors_dir=descriptors_dir,
            )

            descriptor_files = list(descriptors_dir.glob("*.json"))
            self.assertEqual(1, len(descriptor_files))
            self.assertEqual(
                descriptor,
                json.loads(descriptor_files[0].read_text(encoding="utf-8")),
            )
