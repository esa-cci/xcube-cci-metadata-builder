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
