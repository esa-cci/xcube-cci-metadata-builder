from unittest import TestCase

from xcube_cci_metadata_builder.state_checks import (
    CheckConfig,
    _choose_variables,
    _get_common_open_params,
    _get_title,
    check_data_id,
    get_geodataframe_time_range,
    get_region,
)


class _Descriptor:
    bbox = [0.0, 1.0, 10.0, 11.0]
    spatial_res = 1.0
    time_range = ("2000-01-01", "2000-01-31")


class StateChecksTest(TestCase):
    def test_get_region_returns_inner_bbox(self):
        region = get_region(_Descriptor(), CheckConfig(random_seed=1))

        self.assertEqual(4, len(region))
        self.assertGreaterEqual(region[0], 0.0)
        self.assertGreaterEqual(region[1], 1.0)
        self.assertLessEqual(region[2], 10.0)
        self.assertLessEqual(region[3], 11.0)

    def test_get_geodataframe_time_range_uses_center_window(self):
        time_range = get_geodataframe_time_range(_Descriptor())

        self.assertEqual(("2000-01-11", "2000-01-21"), time_range)

    def test_get_title_returns_none_for_missing_title(self):
        class Descriptor:
            attrs = {}

        self.assertIsNone(_get_title(Descriptor()))

    def test_get_title_falls_back_to_store_title(self):
        class Descriptor:
            attrs = {}

        class Store:
            def get_title(self, data_id):
                return f"Catalogue title for {data_id}"

        self.assertEqual(
            "Catalogue title for esacci.TEST",
            _get_title(Descriptor(), Store(), "esacci.TEST"),
        )

    def test_get_title_prefers_descriptor_title(self):
        class Descriptor:
            attrs = {"title": "Descriptor title"}

        class Store:
            def get_title(self, data_id):
                return "Store title"

        self.assertEqual("Descriptor title", _get_title(Descriptor(), Store(), "id"))

    def test_choose_variables_is_deterministic_for_many_variables(self):
        variables = ["a", "b", "c", "d", "e"]

        selected = _choose_variables(variables, CheckConfig(random_seed=7))

        self.assertEqual(selected, _choose_variables(variables, CheckConfig(random_seed=7)))
        self.assertEqual(2, len(selected))

    def test_get_common_open_params_includes_place_names(self):
        class Items:
            enum = ["AREA_1", "AREA_2"]

        class PlaceNames:
            items = Items()

        class Schema:
            properties = {"place_names": PlaceNames()}

        class Descriptor:
            data_vars = {"a": object()}
            open_params_schema = Schema()

        params = _get_common_open_params(Descriptor(), CheckConfig())

        self.assertEqual(["a"], params["variable_names"])
        self.assertEqual(["AREA_1"], params["place_names"])

    def test_check_data_id_returns_error_result_on_exception(self):
        class Store:
            def describe_data(self, data_id, data_type=None):
                raise RuntimeError("broken")

        result = check_data_id(Store(), "id", "dataset", CheckConfig(timeout_seconds=0))

        self.assertEqual("error", result.status)
        self.assertEqual("RuntimeError", result.error["type"])
