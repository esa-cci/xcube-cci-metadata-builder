"""Command line interface for xcube-cci metadata builder."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from textwrap import dedent

from .state_checks import CheckConfig
from .constants import DATA_TYPES
from .result_store import ResultStore
from .run_state_checks import run_state_checks
from .state_render import render_state_files


def _parse_data_types(value: str) -> tuple[str, ...]:
    data_types = tuple(item.strip() for item in value.split(",") if item.strip())
    unknown = sorted(set(data_types).difference(DATA_TYPES))
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Unsupported data type(s): {', '.join(unknown)}"
        )
    return data_types


def _add_render_states_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "render-states",
        help="render xcube-cci state files from persisted per-data-ID results",
        description=(
            "Render dataset_states.json, datatree_states.json, "
            "geodataframe_states.json, and vectordatacube_states.json from "
            "persisted per-data-ID result files."
        ),
        epilog=dedent(
            """\
            examples:
              cci-meta render-states \\
                --results-dir work/results \\
                --previous-states-dir ../xcube-cci/xcube_cci/data \\
                --output-dir ../xcube-cci-registry/states
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="directory containing per-data-ID result JSON files",
    )
    parser.add_argument(
        "--previous-states-dir",
        required=True,
        type=Path,
        help="directory containing existing *_states.json files for curated fields",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="directory where rendered *_states.json files will be written",
    )
    parser.set_defaults(func=_render_states)


def _add_run_checks_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "run-checks",
        help="run live xcube-cci checks and persist per-data-ID results",
        description=(
            "Run live xcube-cci ODP checks and write one result JSON per data "
            "ID. Existing result files are skipped by default so interrupted "
            "runs can be resumed."
        ),
        epilog=dedent(
            """\
            examples:
              cci-meta run-checks --results-dir work/results

              cci-meta run-checks \\
                --results-dir work/results \\
                --data-types geodataframe

              cci-meta run-checks \\
                --results-dir work/results \\
                --data-types dataset,datatree \\
                --limit 10

              cci-meta run-checks \\
                --results-dir work/results \\
                --data-id esacci.AEROSOL.5-days.L3C.AEX.GOMOS.Envisat.AERGOM.3-00.r1
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store-id",
        default="esa-cci",
        help="xcube data store ID to check (default: %(default)s)",
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="directory where per-data-ID result JSON files will be written",
    )
    parser.add_argument(
        "--data-types",
        type=_parse_data_types,
        default=DATA_TYPES,
        metavar="TYPES",
        help=(
            "comma-separated data types to check; choices: "
            "dataset, datatree, geodataframe, vectordatacube "
            "(default: all)"
        ),
    )
    parser.add_argument(
        "--data-id",
        dest="data_ids",
        action="append",
        metavar="ID",
        help=(
            "specific data ID to check; may be supplied multiple times; "
            "when set, listing all data IDs is skipped"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="maximum number of data IDs to check, useful for trial runs",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="timeout in seconds for each live operation (default: %(default)s)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="re-check data IDs even if result files already exist",
    )
    parser.set_defaults(func=_run_checks)


def _render_states(args: argparse.Namespace) -> int:
    written = render_state_files(
        result_store=ResultStore(args.results_dir),
        previous_states_dir=args.previous_states_dir,
        output_dir=args.output_dir,
    )
    for data_type, path in written.items():
        print(f"{data_type}: {path}")
    return 0


def _run_checks(args: argparse.Namespace) -> int:
    from xcube.core.store import new_data_store

    store = new_data_store(args.store_id)
    summary = run_state_checks(
        store=store,
        result_store=ResultStore(args.results_dir),
        data_types=args.data_types,
        data_ids=args.data_ids,
        resume=not args.no_resume,
        limit=args.limit,
        config=CheckConfig(timeout_seconds=args.timeout),
    )
    print(f"checked: {summary.checked}")
    print(f"skipped: {summary.skipped}")
    print(f"errors: {summary.errors}")
    return 1 if summary.errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cci-meta",
        description="Build xcube-cci-registry metadata artifacts.",
        epilog=dedent(
            """\
            common commands:
              cci-meta run-checks --results-dir work/results --limit 10
              cci-meta run-checks --results-dir work/results --data-types geodataframe
              cci-meta render-states --results-dir work/results --previous-states-dir ../xcube-cci/xcube_cci/data --output-dir ../xcube-cci-registry/states
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_run_checks_parser(subparsers)
    _add_render_states_parser(subparsers)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
