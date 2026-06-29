"""Command line interface for xcube-cci metadata builder."""

from __future__ import annotations

import argparse
from pathlib import Path

from .result_store import ResultStore
from .state_render import render_state_files


def _add_render_states_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "render-states",
        help="render xcube-cci state files from persisted per-data-ID results",
    )
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--previous-states-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.set_defaults(func=_render_states)


def _render_states(args: argparse.Namespace) -> int:
    written = render_state_files(
        result_store=ResultStore(args.results_dir),
        previous_states_dir=args.previous_states_dir,
        output_dir=args.output_dir,
    )
    for data_type, path in written.items():
        print(f"{data_type}: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xcube-cci-metadata-builder")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_render_states_parser(subparsers)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
