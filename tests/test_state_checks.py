from unittest import TestCase
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import Point

from xcube_cci_metadata_builder.state_checks import (
    CheckConfig,
    CheckTimeoutError,
    _choose_variables,
    _get_common_open_params,
    _get_title,
    check_data_id,
    get_geodataframe_time_range,
    get_region,
    run_with_timeout,
    subset_dataset_like_for_write,
    write_kml,
    write_to_local_store,
    write_zarr,
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

    def test_write_to_local_store_uses_ect_store(self):
        data = xr.Dataset({"a": ("x", [1, 2])})

        write_to_local_store(data, "esacci.TEST", ".zarr", "zarr")

    def test_write_to_local_store_retries_non_empty_temp_directory(self):
        calls = []

        def write_once(data, data_id, suffix, format_id):
            calls.append((data, data_id, suffix, format_id))
            if len(calls) == 1:
                raise OSError("Directory not empty")

        with patch(
            "xcube_cci_metadata_builder.state_checks._write_to_single_local_store",
            side_effect=write_once,
        ):
            write_to_local_store(object(), "esacci.TEST", ".zarr", "zarr")

        self.assertEqual(2, len(calls))

    def test_run_with_timeout_retries_timeout_error(self):
        calls = []

        def operation():
            calls.append(None)
            if len(calls) == 1:
                raise CheckTimeoutError("timeout")
            return "ok"

        result = run_with_timeout(operation, seconds=0, retries=1)

        self.assertEqual("ok", result)
        self.assertEqual(2, len(calls))

    def test_write_zarr_uses_local_ect_store(self):
        data = xr.Dataset({"a": ("x", [1, 2])})

        write_zarr(data, "esacci.TEST")

    def test_write_kml_uses_local_ect_store(self):
        data = gpd.GeoDataFrame(
            pd.DataFrame({"value": [1]}),
            geometry=[Point(0.0, 0.0)],
            crs="EPSG:4326",
        )

        write_kml(data, "esacci.TEST")

    def test_subset_dataset_like_for_write_limits_variables_and_dimensions(self):
        data = xr.Dataset(
            {
                "a": (("time", "lat"), np.ones((30, 20))),
                "b": (("time", "lat"), np.ones((30, 20))),
                "c": (("time", "lat"), np.ones((30, 20))),
            }
        )

        subset = subset_dataset_like_for_write(data)

        self.assertEqual(["a", "b"], list(subset.data_vars))
        self.assertEqual(10, subset.sizes["time"])
        self.assertEqual(10, subset.sizes["lat"])

    def test_subset_dataset_like_for_write_keeps_small_dataset(self):
        data = xr.Dataset({"a": ("x", [1, 2])})

        subset = subset_dataset_like_for_write(data)

        self.assertIs(data, subset)

    def test_dataset_check_adds_write_zarr_flag(self):
        class Descriptor:
            data_type = "dataset"
            data_vars = {"a": object()}
            attrs = {"title": "Dataset"}

            def to_dict(self):
                return {
                    "data_type": "dataset",
                    "attrs": {"title": "Dataset"},
                }

        class Store:
            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                return xr.Dataset({"a": ("x", [1, 2])})

        result = check_data_id(
            Store(), "esacci.TEST", "dataset", CheckConfig(timeout_seconds=0)
        )

        self.assertEqual("ok", result.status)
        self.assertIn("write_zarr", result.state_entry["verification_flags"])
        self.assertEqual(
            {"data_type": "dataset", "attrs": {"title": "Dataset"}},
            result.descriptor,
        )

    def test_dataset_write_uses_local_subset(self):
        class Descriptor:
            data_type = "dataset"
            data_vars = {name: object() for name in ("a", "b", "c", "d")}
            attrs = {"title": "Dataset"}

        class Store:
            def __init__(self):
                self.open_params = []

            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                self.open_params.append(open_params)
                ds = xr.Dataset(
                    {
                        name: (("time", "lat"), [[1] * 20] * 30)
                        for name in ("a", "b", "c", "d")
                    }
                )
                ds.attrs["open_params"] = dict(open_params)
                return ds

        def assert_write_subset(data, data_id: str, retries: int = 1):
            self.assertLessEqual(len(data.data_vars), 2)
            self.assertLessEqual(data.sizes["time"], 10)
            self.assertLessEqual(data.sizes["lat"], 10)

        store = Store()
        with patch(
            "xcube_cci_metadata_builder.state_checks.write_zarr",
            side_effect=assert_write_subset,
        ):
            result = check_data_id(
                store, "esacci.TEST", "dataset", CheckConfig(timeout_seconds=0)
            )

        self.assertEqual("ok", result.status)
        self.assertEqual(1, len(store.open_params))
        self.assertEqual(["open", "write_zarr"], result.state_entry["verification_flags"])

    def test_dataset_check_preserves_flags_and_continues_after_step_error(self):
        class Descriptor:
            data_type = "dataset"
            data_vars = {"a": object()}
            attrs = {"title": "Dataset"}
            dims = {"time": 3}
            time_range = ("2000-01-01", "2000-01-03")
            time_period = "1D"
            bbox = [0.0, 0.0, 10.0, 10.0]
            spatial_res = 1.0

            def to_dict(self):
                return {
                    "data_type": "dataset",
                    "attrs": {"title": "Dataset"},
                }

        class Store:
            def __init__(self):
                self.open_params = []

            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                self.open_params.append(open_params)
                if "time_range" in open_params:
                    raise RuntimeError("temporal subset failed")
                return xr.Dataset({"a": ("time", [1, 2, 3])})

        with patch("xcube_cci_metadata_builder.state_checks.write_zarr"):
            result = check_data_id(
                Store(), "esacci.TEST", "dataset", CheckConfig(timeout_seconds=0)
            )

        self.assertEqual("error", result.status)
        self.assertEqual("RuntimeError", result.error["type"])
        self.assertEqual(
            {"data_type": "dataset", "attrs": {"title": "Dataset"}},
            result.descriptor,
        )
        self.assertEqual(
            ["open", "constrain_region", "write_zarr"],
            result.state_entry["verification_flags"],
        )
        self.assertEqual(["constrain_time"], [item["check"] for item in result.error["checks"]])

    def test_geodataframe_write_uses_local_subset(self):
        class FeatureSchema:
            def to_dict(self):
                return {"properties": {"value": {}, "other": {}, "geometry": {}}}

        class Descriptor:
            feature_schema = FeatureSchema()
            attrs = {"title": "GeoDataFrame"}
            time_range = ("2000-01-01", "2000-01-31")

        class Store:
            def __init__(self):
                self.open_params = []

            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                self.open_params.append(open_params)
                gdf = gpd.GeoDataFrame(
                    pd.DataFrame({"value": list(range(20)), "other": list(range(20))}),
                    geometry=[Point(float(value), 0.0) for value in range(20)],
                    crs="EPSG:4326",
                )
                gdf.attrs["open_params"] = dict(open_params)
                return gdf

        def assert_write_subset(data, data_id: str, retries: int = 1):
            self.assertEqual(10, len(data))

        store = Store()
        with patch(
            "xcube_cci_metadata_builder.state_checks.write_kml",
            side_effect=assert_write_subset,
        ):
            result = check_data_id(
                store, "esacci.TEST", "geodataframe", CheckConfig(timeout_seconds=0)
            )

        self.assertEqual("ok", result.status)
        self.assertEqual(3, len(store.open_params))

    def test_local_store_write_failure_returns_error_result(self):
        class Descriptor:
            data_type = "dataset"
            data_vars = {"a": object()}
            attrs = {"title": "Dataset"}

        class Store:
            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                return object()

        result = check_data_id(
            Store(), "esacci.TEST", "dataset", CheckConfig(timeout_seconds=0)
        )

        self.assertEqual("error", result.status)
        self.assertIn(result.error["type"], {"DataStoreError", "TypeError", "ValueError"})

    def test_datatree_write_failure_returns_error_result(self):
        class Descriptor:
            data_type = "datatree"
            data_vars = {"a": object()}
            attrs = {"title": "DataTree"}

        class Store:
            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                return xr.DataTree.from_dict(
                    {"/": xr.Dataset(), "/child": xr.Dataset({"a": ("x", [1, 2])})}
                )

        result = check_data_id(
            Store(), "esacci.TEST", "datatree", CheckConfig(timeout_seconds=0)
        )

        self.assertEqual("error", result.status)
        self.assertEqual("ValidationError", result.error["type"])
        self.assertEqual(["open"], result.state_entry["verification_flags"])

    def test_vectordatacube_geometry_write_failure_returns_error_result(self):
        class Descriptor:
            data_type = "vectordatacube"
            data_vars = {"value": object()}
            attrs = {"title": "VectorDataCube"}

        class Store:
            def describe_data(self, data_id, data_type=None):
                return Descriptor()

            def open_data(self, data_id, **open_params):
                return xr.Dataset(
                    {"value": (("time", "geometry"), np.ones((2, 2)))},
                    coords={
                        "time": np.array(
                            ["2000-01-01", "2000-01-02"], dtype="datetime64[ns]"
                        ),
                        "geometry": np.array(
                            [Point(0.0, 0.0), Point(1.0, 1.0)], dtype=object
                        ),
                    },
                )

        result = check_data_id(
            Store(), "esacci.TEST", "vectordatacube", CheckConfig(timeout_seconds=0)
        )

        self.assertEqual("error", result.status)
        self.assertEqual("DataStoreError", result.error["type"])
        self.assertEqual(["open"], result.state_entry["verification_flags"])
