"""Live checks for xcube-cci state generation."""

from __future__ import annotations

import random
import re
import signal
import tempfile
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from .constants import DATASET, DATATREE, GEODATAFRAME, VECTORDATACUBE
from .descriptors import descriptor_to_dict
from .result_store import BuilderResult

TIMEOUT_SECONDS = 120
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_KML_ACCESSOR_REGISTERED = False


class CheckTimeoutError(TimeoutError):
    """Raised when a single check exceeds its timeout."""


class CheckFailedError(Exception):
    """Raised after one or more non-fatal check steps failed."""

    def __init__(
        self,
        state_entry: dict[str, Any],
        errors: list[dict[str, Any]],
        descriptor: dict[str, Any] | None = None,
    ):
        self.state_entry = state_entry
        self.errors = errors
        self.descriptor = descriptor
        first_error = errors[0] if errors else {}
        super().__init__(first_error.get("message", "Check failed."))


@dataclass(frozen=True)
class CheckConfig:
    """Configuration for one live data check."""

    timeout_seconds: int = TIMEOUT_SECONDS
    random_seed: int = 42


@dataclass(frozen=True)
class CheckResult:
    """Successful live check data before it is persisted."""

    state_entry: dict[str, Any]
    descriptor: dict[str, Any] | None = None


@contextmanager
def timeout(seconds: int) -> Iterator[None]:
    """Limit one operation using ``SIGALRM`` where available."""

    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def alarm_handler(signum, frame):
        raise CheckTimeoutError(f"Time out after {seconds} seconds.")

    previous_handler = signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def check_data_id(
    store: Any,
    data_id: str,
    data_type: str,
    config: CheckConfig | None = None,
) -> BuilderResult:
    """Check one data ID and return a persistable builder result."""

    config = config or CheckConfig()
    try:
        checker = _get_checker(data_type)
        check_result = checker(store, data_id, config)
        return BuilderResult(
            data_id=data_id,
            data_type=data_type,
            status="ok",
            state_entry=check_result.state_entry,
            descriptor=check_result.descriptor,
        )
    except CheckFailedError as exception:
        first_error = exception.errors[0] if exception.errors else {}
        return BuilderResult(
            data_id=data_id,
            data_type=data_type,
            status="error",
            state_entry=exception.state_entry,
            descriptor=exception.descriptor,
            error={
                "type": first_error.get("type", type(exception).__name__),
                "message": first_error.get("message", str(exception)),
                "traceback": first_error.get("traceback", traceback.format_exc()),
                "checks": exception.errors,
            },
        )
    except Exception as exception:
        return BuilderResult(
            data_id=data_id,
            data_type=data_type,
            status="error",
            error={
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
            },
        )


def _get_checker(data_type: str):
    if data_type == GEODATAFRAME:
        return _check_geodataframe
    if data_type == VECTORDATACUBE:
        return _check_vectordatacube
    if data_type in (DATASET, DATATREE):
        return _check_dataset_like
    raise ValueError(f"Unsupported data type: {data_type!r}")


def _check_error(check_name: str, exception: Exception) -> dict[str, Any]:
    return {
        "check": check_name,
        "type": type(exception).__name__,
        "message": str(exception),
        "traceback": traceback.format_exc(),
    }


def _check_dataset_like(
    store: Any, data_id: str, config: CheckConfig
) -> CheckResult:
    descriptor = store.describe_data(data_id=data_id)
    serialized_descriptor = descriptor_to_dict(descriptor)
    data_type = _descriptor_data_type(descriptor)
    open_params = _get_common_open_params(descriptor, config)
    flags: list[str] = []
    errors: list[dict[str, Any]] = []

    with timeout(config.timeout_seconds):
        data = store.open_data(data_id, **open_params)
    try:
        data_for_checks = _as_dataset(data)
        try:
            _assert_requested_variables(
                data_for_checks, open_params.get("variable_names", [])
            )
            flags.append("open")
        except Exception as exception:
            errors.append(_check_error("open", exception))

        try:
            time_range = get_array_time_range(descriptor, data_for_checks)
            if time_range is not None:
                params = dict(open_params)
                params["time_range"] = time_range
                with timeout(config.timeout_seconds):
                    temporal_data = store.open_data(data_id, **params)
                try:
                    _assert_requested_variables(
                        _as_dataset(temporal_data), params.get("variable_names", [])
                    )
                    flags.append("constrain_time")
                finally:
                    _close_data(temporal_data)
        except Exception as exception:
            errors.append(_check_error("constrain_time", exception))

        try:
            region = get_region(descriptor, config)
            if region is not None:
                params = dict(open_params)
                params["bbox"] = region
                with timeout(config.timeout_seconds):
                    spatial_data = store.open_data(data_id, **params)
                try:
                    _assert_requested_variables(
                        _as_dataset(spatial_data), params.get("variable_names", [])
                    )
                    flags.append("constrain_region")
                finally:
                    _close_data(spatial_data)
        except Exception as exception:
            errors.append(_check_error("constrain_region", exception))

        try:
            write_data_obj = subset_dataset_like_for_write(data)
            with timeout(config.timeout_seconds):
                write_zarr(write_data_obj, data_id)
            flags.append("write_zarr")
        except Exception as exception:
            errors.append(_check_error("write_zarr", exception))
    finally:
        _close_data(data)

    state_entry = {
        "data_type": data_type,
        "verification_flags": flags,
        "title": _get_title(descriptor, store, data_id),
    }
    if errors:
        raise CheckFailedError(state_entry, errors, serialized_descriptor)
    return CheckResult(state_entry=state_entry, descriptor=serialized_descriptor)


def _check_vectordatacube(
    store: Any, data_id: str, config: CheckConfig
) -> CheckResult:
    descriptor = store.describe_data(data_id=data_id, data_type=VECTORDATACUBE)
    serialized_descriptor = descriptor_to_dict(descriptor)
    open_params = _get_common_open_params(descriptor, config)
    with timeout(config.timeout_seconds):
        data = store.open_data(data_id, **open_params)
    flags = ["open"]
    errors: list[dict[str, Any]] = []
    try:
        try:
            write_data_obj = subset_dataset_like_for_write(data)
            with timeout(config.timeout_seconds):
                write_zarr(write_data_obj, data_id)
            flags.append("write_zarr")
        except Exception as exception:
            errors.append(_check_error("write_zarr", exception))
    finally:
        _close_data(data)
    state_entry = {
        "data_type": VECTORDATACUBE,
        "verification_flags": flags,
        "title": _get_title(descriptor, store, data_id),
    }
    if errors:
        raise CheckFailedError(state_entry, errors, serialized_descriptor)
    return CheckResult(state_entry=state_entry, descriptor=serialized_descriptor)


def _check_geodataframe(store: Any, data_id: str, config: CheckConfig) -> CheckResult:
    descriptor = store.describe_data(data_id=data_id, data_type=GEODATAFRAME)
    serialized_descriptor = descriptor_to_dict(descriptor)
    open_params = _get_geodataframe_open_params(descriptor, config)
    flags: list[str] = []
    errors: list[dict[str, Any]] = []

    with timeout(config.timeout_seconds):
        gdf = store.open_data(data_id, **open_params)
    flags.append("open")

    try:
        time_range = get_geodataframe_time_range(descriptor)
        if time_range is not None:
            params = dict(open_params)
            params["time_range"] = time_range
            with timeout(config.timeout_seconds):
                gdf = store.open_data(data_id, **params)
            flags.append("constrain_time")
    except Exception as exception:
        errors.append(_check_error("constrain_time", exception))

    try:
        region = get_geodataframe_region(gdf, descriptor)
        if region is not None:
            params = dict(open_params)
            params["bbox"] = region
            with timeout(config.timeout_seconds):
                store.open_data(data_id, **params)
            flags.append("constrain_region")
    except Exception as exception:
        errors.append(_check_error("constrain_region", exception))

    try:
        write_gdf = subset_geodataframe_for_write(gdf)
        with timeout(config.timeout_seconds):
            write_kml(write_gdf, data_id)
        flags.append("write_kml")
    except Exception as exception:
        errors.append(_check_error("write_kml", exception))

    state_entry = {
        "data_type": GEODATAFRAME,
        "verification_flags": flags,
        "title": _get_title(descriptor, store, data_id),
    }
    if errors:
        raise CheckFailedError(state_entry, errors, serialized_descriptor)
    return CheckResult(state_entry=state_entry, descriptor=serialized_descriptor)


def _get_common_open_params(descriptor: Any, config: CheckConfig) -> dict[str, Any]:
    params: dict[str, Any] = {}
    variable_names = _choose_variables(
        list((getattr(descriptor, "data_vars", None) or {}).keys()),
        config,
    )
    if variable_names:
        params["variable_names"] = variable_names
    properties = getattr(getattr(descriptor, "open_params_schema", None), "properties", {})
    place_names = properties.get("place_names") if properties else None
    if place_names is not None:
        params["place_names"] = [place_names.items.enum[0]]
    return params


def _get_geodataframe_open_params(descriptor: Any, config: CheckConfig) -> dict[str, Any]:
    params: dict[str, Any] = {}
    feature_schema = descriptor.feature_schema.to_dict()
    variable_names = list(feature_schema.get("properties", {}).keys())
    for coord_name in ("geometry", "time", "lat", "lon", "latitude", "longitude"):
        if coord_name in variable_names:
            variable_names.remove(coord_name)
    variable_names = _choose_variables(variable_names, config)
    if variable_names:
        params["variable_names"] = variable_names
    properties = getattr(getattr(descriptor, "open_params_schema", None), "properties", {})
    place_names = properties.get("place_names") if properties else None
    if place_names is not None:
        params["place_names"] = [place_names.items.enum[0]]
    return params


def _choose_variables(variable_names: list[str], config: CheckConfig) -> list[str]:
    if len(variable_names) > 3:
        randomizer = random.Random(config.random_seed)
        return randomizer.sample(variable_names, k=min(2, len(variable_names)))
    return list(variable_names)


def get_array_time_range(descriptor: Any, data: Any) -> tuple[str, str] | None:
    descriptor_range = getattr(descriptor, "time_range", None)
    dims = getattr(descriptor, "dims", None)
    time_period = getattr(descriptor, "time_period", None)
    if (
        descriptor_range is not None
        and dims is not None
        and dims.get("time", 0) > 2
        and time_period is not None
    ):
        time_value = int(time_period[:-1])
        time_unit = time_period[-1]
        if time_unit == "M":
            time_unit = "D"
            time_value *= 31
        elif time_unit == "Y":
            time_unit = "D"
            time_value *= 366
        time_start = _parse_date(descriptor_range[0])
        time_end = time_start + _to_timedelta(time_value, time_unit)
        return _format_date(time_start), _format_date(time_end)

    time_name = None
    if "time" in data:
        time_name = "time"
    elif "t" in data:
        time_name = "t"
    if time_name is None:
        return None
    start_time = data[time_name][0].values
    end_time_index = min(2, len(data[time_name]) - 1)
    end_time = data[time_name][end_time_index].values
    return _format_date(start_time), _format_date(end_time)


def get_geodataframe_time_range(descriptor: Any) -> tuple[str, str] | None:
    time_range = getattr(descriptor, "time_range", None)
    if not time_range:
        return None
    time_start = _parse_date(time_range[0])
    time_end = _parse_date(time_range[-1])
    center_time = time_start + (time_end - time_start) / 2
    five_days = timedelta(days=5)
    return (
        _format_date(center_time - five_days),
        _format_date(center_time + five_days),
    )


def get_region(descriptor: Any, config: CheckConfig) -> list[float] | None:
    bbox = getattr(descriptor, "bbox", None)
    if bbox is None:
        return None
    spatial_res = getattr(descriptor, "spatial_res", None) or 1.0
    minx = float(bbox[0])
    miny = float(bbox[1])
    maxx = float(bbox[2]) - spatial_res * 2.0
    maxy = float(bbox[3]) - spatial_res * 2.0
    if maxx <= minx or maxy <= miny:
        return None
    randomizer = random.Random(config.random_seed)
    x = randomizer.uniform(minx, maxx)
    y = randomizer.uniform(miny, maxy)
    return [
        float(f"{x:.5f}"),
        float(f"{y:.5f}"),
        float(f"{x + spatial_res * 2.0:.5f}"),
        float(f"{y + spatial_res * 2.0:.5f}"),
    ]


def get_geodataframe_region(gdf: Any, descriptor: Any) -> list[float] | None:
    if gdf is not None and "geometry" in getattr(gdf, "columns", []):
        minx, miny, maxx, maxy = gdf.geometry.total_bounds
    else:
        bbox = getattr(descriptor, "bbox", None)
        if bbox is None:
            return None
        minx, miny, maxx, maxy = bbox
    width = (maxx - minx) / 2
    return [minx, miny, maxx - width, maxy]


def _as_dataset(data: Any) -> Any:
    if hasattr(data, "children") and hasattr(data, "get"):
        keys = list(data.keys())
        if keys:
            return data.get(keys[0]).to_dataset()
    return data


def subset_dataset_like_for_write(data: Any) -> Any:
    """Return a small local subset suitable for write verification."""

    if hasattr(data, "children") and hasattr(data, "map_over_datasets"):
        def subset_node(dataset):
            subset = _subset_dataset_for_write(dataset)
            return subset

        return data.map_over_datasets(subset_node)

    return _subset_dataset_for_write(data)


def _subset_dataset_for_write(data: Any) -> Any:
    subset = data

    data_vars = list(getattr(subset, "data_vars", {}) or {})
    if len(data_vars) > 2 and hasattr(subset, "__getitem__"):
        subset = subset[data_vars[:2]]

    dims = getattr(subset, "sizes", None) or getattr(subset, "dims", None) or {}
    indexers = {
        dim_name: slice(0, 10)
        for dim_name, dim_size in dict(dims).items()
        if dim_size is not None and dim_size > 10
    }
    if indexers and hasattr(subset, "isel"):
        subset = subset.isel(indexers)
    return subset


def subset_geodataframe_for_write(gdf: Any) -> Any:
    """Return a small local GeoDataFrame subset for write verification."""

    if len(gdf) <= 10:
        return gdf
    return gdf.head(10)


def _close_data(data: Any) -> None:
    close = getattr(data, "close", None)
    if close is not None:
        close()


def _assert_requested_variables(data: Any, variable_names: list[str]) -> None:
    if not variable_names:
        return
    data_vars = getattr(data, "data_vars", {})
    present = [var_name for var_name in variable_names if var_name in data_vars]
    if not present:
        raise ValueError(f"Requested variables {variable_names!r} are not in dataset.")


def write_zarr(data: Any, data_id: str) -> None:
    """Write *data* to a temporary local ECT store as Zarr."""

    write_to_local_store(data, data_id, suffix=".zarr", format_id="zarr")


def write_kml(data: Any, data_id: str) -> None:
    """Write *data* to a temporary local ECT store as KML."""

    write_to_local_store(data, data_id, suffix=".kml", format_id="kml")


def write_to_local_store(
    data: Any,
    data_id: str,
    suffix: str,
    format_id: str | None = None,
) -> None:
    """Write *data* to a temporary local ECT file store."""

    local_data_id = f"{_safe_name(data_id)}{suffix}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        if format_id == "kml":
            _ensure_ect_kml_accessor_registered()
        from esa_climate_toolbox.core.ds import (
            add_local_store,
            get_store,
            remove_store,
            write_data,
        )

        store_id = add_local_store(root=tmp_dir, max_depth=3, persist=False)
        try:
            written_id = write_data(
                data=data,
                data_id=local_data_id,
                store_id=store_id,
                format_id=format_id,
            )
            if not get_store(store_id).has_data(written_id):
                raise RuntimeError(
                    f"Local ECT store did not report written data {written_id!r}."
                )
        finally:
            remove_store(store_id, persist=False)


def _ensure_ect_kml_accessor_registered() -> None:
    global _KML_ACCESSOR_REGISTERED
    if _KML_ACCESSOR_REGISTERED:
        return

    from esa_climate_toolbox.ds.geodataframe import GeoDataFrameKmlFsDataAccessor
    from xcube.core.store.fs.registry import register_fs_data_accessor_class

    register_fs_data_accessor_class(GeoDataFrameKmlFsDataAccessor)
    _KML_ACCESSOR_REGISTERED = True


def _safe_name(data_id: str) -> str:
    safe_name = _SAFE_NAME_PATTERN.sub("_", data_id).strip("._")
    return safe_name or "data"


def _descriptor_data_type(descriptor: Any) -> str:
    data_type = getattr(descriptor, "data_type", None)
    alias = getattr(data_type, "alias", data_type)
    if alias in (DATASET, DATATREE, GEODATAFRAME, VECTORDATACUBE):
        return alias
    return str(alias)


def _get_title(descriptor: Any, store: Any = None, data_id: str | None = None) -> str | None:
    attrs = getattr(descriptor, "attrs", None) or {}
    title = attrs.get("title")
    if title:
        return title
    if store is not None and data_id is not None and hasattr(store, "get_title"):
        try:
            return store.get_title(data_id) or None
        except Exception:
            return None
    return None


def _format_date(value: Any) -> str:
    return _parse_date(value).strftime("%Y-%m-%d")


def _parse_date(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    return datetime.fromisoformat(text[:10])


def _to_timedelta(value: int, unit: str) -> timedelta:
    if unit == "D":
        return timedelta(days=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "s":
        return timedelta(seconds=value)
    raise ValueError(f"Unsupported time period unit: {unit!r}")
