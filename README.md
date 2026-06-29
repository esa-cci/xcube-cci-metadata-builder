# xcube-cci-metadata-builder

This repository contains the builder for `xcube-cci-registry` artifacts.

The first implementation focus is the generation of xcube-cci state files:

- `dataset_states.json`
- `datatree_states.json`
- `geodataframe_states.json`
- `vectordatacube_states.json`

Builder runs are expected to be long and failure-prone, so intermediate results
are persisted per data ID. Final state files are rendered from those persisted
results and merged with manually curated fields from existing xcube-cci state
files.

## Current CLI

Run live checks and persist one result JSON per data ID:

```bash
xcube-cci-metadata-builder run-checks \
  --store-id esa-cci \
  --results-dir work/results
```

Useful options:

- `--data-types dataset,datatree,geodataframe,vectordatacube`
- `--data-id <id>` to check one or more specific data IDs
- `--limit <n>` for small trial runs
- `--no-resume` to ignore existing result files
- `--timeout <seconds>` for each live operation

Render state files from persisted per-data-ID result files:

```bash
xcube-cci-metadata-builder render-states \
  --results-dir work/results \
  --previous-states-dir ../xcube-cci/xcube_cci/data \
  --output-dir ../xcube-cci-registry/states
```

The render step preserves these curated fields from previous states:

- `places`
- `var_names`
- `pattern`
