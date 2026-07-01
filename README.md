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
files. The same per-data-ID results may also carry descriptors from
`describe_data()`, which can be rendered into the registry descriptor cache
together with the matching state update.

## CLI

The package installs two equivalent command names:

- `cci-meta`
- `xcube-cci-metadata-builder`

The short form is used in the examples below.

Run live checks and persist one result JSON per data ID:

```bash
cci-meta run-checks \
  --store-id esa-cci \
  --results-dir work/results
```

Choose where per-data-ID result files are written:

```bash
cci-meta run-checks \
  --results-dir /path/to/work/results
```

Run only one data type:

```bash
cci-meta run-checks \
  --results-dir work/results \
  --data-types geodataframe
```

Run multiple selected data types:

```bash
cci-meta run-checks \
  --results-dir work/results \
  --data-types dataset,datatree
```

Run only one or a few specific data IDs:

```bash
cci-meta run-checks \
  --results-dir work/results \
  --data-id esacci.AEROSOL.5-days.L3C.AEX.GOMOS.Envisat.AERGOM.3-00.r1
```

Limit a trial run to a small number of data IDs:

```bash
cci-meta run-checks \
  --results-dir work/results \
  --limit 10
```

Force a rerun instead of resuming from existing result files:

```bash
cci-meta run-checks \
  --results-dir work/results \
  --no-resume
```

Set the timeout for each live operation:

```bash
cci-meta run-checks \
  --results-dir work/results \
  --timeout 300
```

Important `run-checks` options:

- `--data-types dataset,datatree,geodataframe,vectordatacube`
- `--data-id <id>` to check one or more specific data IDs
- `--limit <n>` for small trial runs
- `--no-resume` to ignore existing result files
- `--timeout <seconds>` for each live operation

Build descriptor files directly in a registry checkout without running state
checks:

```bash
cci-meta build-descriptors \
  --registry-dir ../xcube-cci-registry
```

Restrict descriptor generation to selected data types and a wildcard pattern:

```bash
cci-meta build-descriptors \
  --registry-dir ../xcube-cci-registry \
  --data-types dataset \
  --name-pattern "LST.mon.*.v4"
```

The command writes descriptor JSON files below
`<registry-dir>/descriptors/<store-id>`, for example
`../xcube-cci-registry/descriptors/esa-cci`.

Render state files from persisted per-data-ID result files:

```bash
cci-meta render-states \
  --results-dir work/results \
  --previous-states-dir ../xcube-cci/xcube_cci/data \
  --output-dir ../xcube-cci-registry/states \
  --descriptors-dir ../xcube-cci-registry/descriptors/esa-cci
```

The render step preserves these curated fields from previous states:

- `places`
- `var_names`
- `pattern`
