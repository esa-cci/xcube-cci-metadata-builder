from unittest import TestCase

from xcube_cci_metadata_builder.state_merge import merge_manual_fields, merge_state_file


class StateMergeTest(TestCase):
    def test_merge_manual_fields_preserves_curated_values(self):
        generated = {
            "data_type": "datatree",
            "verification_flags": ["open"],
            "title": "Generated",
        }
        previous = {
            "data_type": "datatree",
            "verification_flags": ["open"],
            "title": "Previous",
            "places": ["AREA_1"],
            "var_names": ["burned_area"],
            "pattern": "{var_name}-{place}",
        }

        merged = merge_manual_fields(generated, previous)

        self.assertEqual("Generated", merged["title"])
        self.assertEqual(["AREA_1"], merged["places"])
        self.assertEqual(["burned_area"], merged["var_names"])
        self.assertEqual("{var_name}-{place}", merged["pattern"])

    def test_merge_state_file_sorts_by_data_id(self):
        merged = merge_state_file(
            {
                "b": {"data_type": "dataset", "verification_flags": [], "title": "B"},
                "a": {"data_type": "dataset", "verification_flags": [], "title": "A"},
            },
            None,
        )

        self.assertEqual(["a", "b"], list(merged))

    def test_merge_manual_fields_uses_previous_title_if_generated_title_is_missing(self):
        merged = merge_manual_fields(
            {
                "data_type": "dataset",
                "verification_flags": ["open"],
                "title": None,
            },
            {
                "data_type": "dataset",
                "verification_flags": ["open"],
                "title": "Previous title",
            },
        )

        self.assertEqual("Previous title", merged["title"])

    def test_merge_state_file_uses_data_id_as_final_title_fallback(self):
        merged = merge_state_file(
            {
                "esacci.TEST": {
                    "data_type": "dataset",
                    "verification_flags": ["open"],
                    "title": "",
                }
            },
            None,
        )

        self.assertEqual("esacci.TEST", merged["esacci.TEST"]["title"])
