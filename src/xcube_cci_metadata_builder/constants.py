"""Shared constants for xcube-cci metadata builder artifacts."""

from __future__ import annotations

DATASET = "dataset"
DATATREE = "datatree"
GEODATAFRAME = "geodataframe"
VECTORDATACUBE = "vectordatacube"

DATA_TYPES = (DATASET, DATATREE, GEODATAFRAME, VECTORDATACUBE)

STATE_FILE_NAMES = {
    DATASET: "dataset_states.json",
    DATATREE: "datatree_states.json",
    GEODATAFRAME: "geodataframe_states.json",
    VECTORDATACUBE: "vectordatacube_states.json",
}

MANUAL_STATE_FIELDS = ("places", "var_names", "pattern")
