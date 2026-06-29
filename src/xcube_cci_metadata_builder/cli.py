"""Command line interface for xcube-cci metadata builder."""

from __future__ import annotations

import argparse
from pathlib import Path

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
    )
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--previous-states-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.set_defaults(func=_render_states)


def _add_run_checks_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "run-checks",
        help="run live xcube-cci checks and persist per-data-ID results",
    )
    parser.add_argument("--store-id", default="esa-cci")
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument(
        "--data-types",
        type=_parse_data_types,
        default=DATA_TYPES,
        help="comma-separated data types to check",
    )
    parser.add_argument(
        "--data-id",
        dest="data_ids",
        action="append",
        help="specific data ID to check; may be supplied multiple times",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="re-check data IDs even if a result file already exists",
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
    parser = argparse.ArgumentParser(prog="xcube-cci-metadata-builder")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_run_checks_parser(subparsers)
    _add_render_states_parser(subparsers)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
