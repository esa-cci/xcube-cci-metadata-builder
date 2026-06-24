from datetime import datetime
import json

import pandas as pd
import random

# from esa_climate_toolbox.ds.dataaccess import CciOdpDataFrameOpener
from xcube_cci.dataaccess import CciOdpDataFrameOpener

date_today = datetime.date(datetime.now())

def get_time_range(data_descriptor):
    time_range = data_descriptor.time_range
    five_days = pd.Timedelta(5, "D")
    time_start = pd.Timestamp(time_range[0])
    time_end = pd.Timestamp(time_range[-1])
    time_delta = (time_end - time_start) / 2
    center_time = time_start + time_delta
    time_start = center_time - five_days
    time_end = center_time + five_days
    return time_start.strftime('%Y-%m-%d'), time_end.strftime('%Y-%m-%d')


def get_region_from_descriptor(descriptor):
    bounds = descriptor.bbox
    min_lon = bounds[0]
    min_lat = bounds[1]
    max_lon = bounds[2]
    max_lat = bounds[3]
    d_lon = (max_lon - min_lon) / 2
    max_lon -= d_lon
    return [min_lon, min_lat, max_lon, max_lat]


def get_region(gdf):
    bounds = gdf.geometry.total_bounds
    min_lon = bounds[0]
    min_lat = bounds[1]
    max_lon = bounds[2]
    max_lat = bounds[3]
    d_lon = (max_lon - min_lon) / 2
    max_lon -= d_lon
    return [min_lon, min_lat, max_lon, max_lat]


dfo = CciOdpDataFrameOpener()

ds_names = dfo.dataset_names

invalids = []
last_reached = 0

dataset_states = {}

sum_ds = len(ds_names)
for i, ds_name in enumerate(ds_names):
    if i in invalids:
        print(f"{i}: Dataset '{ds_name}' is confirmed to be problematic.")
        continue
    if i < last_reached:
        print(f"{i}: Already checked dataset '{ds_name}'")
        continue
    print(f"{i}: Checking dataset '{ds_name}' of {sum_ds}")
    dataset_states[ds_name] = {
        "data_type": "geodataframe",
        "verification_flags": [],
        "title": ds_name
    }
    try:
        descriptor = dfo.describe_data([ds_name])[0]
    except:
        print(f"Could not describe '{ds_name}'")
        continue
    features = descriptor.feature_schema.to_dict()
    place_names = descriptor.open_params_schema.properties.get("place_names")
    dataset_states[ds_name] = {
        "data_type": "geodataframe",
        "verification_flags": [],
        "title": dfo.get_title(ds_name)
    }

    var_list = []
    ds_vars = list(features.get("properties", {}).keys())
    to_be_removed = ["geometry", "time", "lat", "lon", "latitude", "longitude"]
    for r in to_be_removed:
        if r in ds_vars:
            ds_vars.remove(r)
    if len(ds_vars) > 3:
        while len(var_list) < 1:
            for var in random.choices(ds_vars, k=2):
                var_list.append(var)
    else:
        var_list = list(ds_vars)

    open_params = dict(
        data_id=ds_name,
        variable_names=var_list
    )
    if place_names is not None:
        open_params["place_names"] = [place_names.items.enum[0]]

    try:
        gdf = dfo.open_data(**open_params)
        print(f"Successfully opened '{ds_name}'")
        dataset_states[ds_name]["verification_flags"].append("open")
    except:
        print(f"Could not open '{ds_name}'")
        continue

    time_range = get_time_range(descriptor)
    open_params["time_range"] = time_range
    try:
        gdf = dfo.open_data(
            **open_params
        )
        print(gdf[0:3])
        print(f"Successfully opened temporal subset '{ds_name}'")
        dataset_states[ds_name]["verification_flags"].append("constrain_time")
    except:
        print(f"Could not open temporal subset of '{ds_name}'")

    open_params.pop("time_range")

    if gdf is not None and "geometry" in gdf.columns:
        spatial_range = get_region(gdf[0:10])
    else:
        spatial_range = get_region_from_descriptor(descriptor)
    try:
        open_params["bbox"] = spatial_range
        sgdf = dfo.open_data(
            **open_params
        )
        print(f"Successfully opened spatial subset '{ds_name}'")
        dataset_states[ds_name]["verification_flags"].append("constrain_region")
    except:
        print(f"Could not open spatial subset of '{ds_name}'")
    dataset_states[ds_name]["verification_flags"].append("write_geojson")

with open(f"esa-cci/{date_today}_geodataframes_DrsID_verification_flags.json", "w") as outfile:
    json.dump(dataset_states, outfile, indent=4)
