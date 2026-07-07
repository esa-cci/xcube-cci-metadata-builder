"""Command line interface for xcube-cci metadata builder."""

from __future__ import annotations

import argparse
import logging
import re
import selectors
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from .build_descriptors import build_descriptors
from .constants import DATA_TYPES
from .registry_build import build_esa_cci_registry
from .result_store import ResultStore
from .run_state_checks import run_state_checks
from .state_checks import CheckConfig
from .state_render import render_state_files

DEFAULT_MAX_RESTARTS = 20


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
                --output-dir ../xcube-cci-registry/states \\
                --descriptors-dir ../xcube-cci-registry/descriptors/esa-cci
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
    parser.add_argument(
        "--descriptors-dir",
        type=Path,
        help=(
            "optional directory where descriptor JSON files from the same "
            "builder results will be written"
        ),
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
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help=(
            "retries for transient live-operation timeouts and temporary "
            "local-write cleanup failures (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(func=_run_checks)


def _add_build_descriptors_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "build-descriptors",
        help="describe data IDs and write descriptor artifacts directly to a registry",
        description=(
            "Describe matching xcube-cci ODP data IDs and write descriptor JSON "
            "files directly to <registry-dir>/descriptors/<store-id>."
        ),
        epilog=dedent(
            """\
            examples:
              cci-meta build-descriptors \\
                --registry-dir ../xcube-cci-registry

              cci-meta build-descriptors \\
                --registry-dir ../xcube-cci-registry \\
                --data-types dataset \\
                --name-pattern "LST.mon.*.v4"
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store-id",
        default="esa-cci",
        help="xcube data store ID to describe (default: %(default)s)",
    )
    parser.add_argument(
        "--registry-dir",
        required=True,
        type=Path,
        help=(
            "target registry repository; descriptors are written below "
            "<registry-dir>/descriptors/<store-id>"
        ),
    )
    parser.add_argument(
        "--data-types",
        type=_parse_data_types,
        default=DATA_TYPES,
        metavar="TYPES",
        help=(
            "comma-separated data types to describe; choices: "
            "dataset, datatree, geodataframe, vectordatacube "
            "(default: all)"
        ),
    )
    parser.add_argument(
        "--name-pattern",
        help=(
            "wildcard pattern for data IDs, for example 'LST.mon.*.v4'; "
            "matches full IDs and contained ID fragments"
        ),
    )
    parser.add_argument(
        "--data-id",
        dest="data_ids",
        action="append",
        metavar="ID",
        help=(
            "specific data ID to describe; may be supplied multiple times; "
            "when set, listing all data IDs is skipped"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="maximum number of descriptors to write, useful for trial runs",
    )
    parser.set_defaults(func=_build_descriptors)


def _add_build_registry_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "build-registry",
        help="build registry.json from rendered registry artifacts",
        description=(
            "Build registry.json entries for the ESA CCI ODP store from "
            "descriptor artifacts and rendered state files in a registry checkout."
        ),
        epilog=dedent(
            """\
            examples:
              cci-meta build-registry \\
                --registry-dir ../xcube-cci-registry
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--registry-dir",
        required=True,
        type=Path,
        help="target registry repository containing descriptors/ and states/",
    )
    parser.add_argument(
        "--store-id",
        default="esa-cci",
        help="store ID whose descriptors should be registered (default: %(default)s)",
    )
    parser.set_defaults(func=_build_registry)


def _render_states(args: argparse.Namespace) -> int:
    written = render_state_files(
        result_store=ResultStore(args.results_dir),
        previous_states_dir=args.previous_states_dir,
        output_dir=args.output_dir,
        descriptors_dir=args.descriptors_dir,
    )
    for data_type, path in written.items():
        print(f"{data_type}: {path}")
    return 0


def _run_checks(args: argparse.Namespace) -> int:
    if not args.run_once and not args.no_resume:
        return _run_checks_supervised(args)

    from xcube.core.store import new_data_store

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    store = new_data_store(args.store_id)
    summary = run_state_checks(
        store=store,
        result_store=ResultStore(args.results_dir),
        data_types=args.data_types,
        data_ids=args.data_ids,
        resume=not args.no_resume,
        limit=args.limit,
        config=CheckConfig(
            timeout_seconds=args.timeout,
            retries=args.retries,
        ),
    )
    print(f"checked: {summary.checked}")
    print(f"skipped: {summary.skipped}")
    print(f"errors: {summary.errors}")
    return 1 if summary.errors else 0


def _run_checks_supervised(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    command = _run_checks_child_command(args)
    restarts = 0
    while True:
        returncode, output = _run_streamed_child(command)
        checked = _parse_count(output, "checked")
        if checked is not None and not _should_continue_after_summary(
            args,
            returncode,
            checked,
        ):
            return returncode

        if checked is not None:
            continue

        restarts += 1
        if restarts > DEFAULT_MAX_RESTARTS:
            return returncode

        logging.getLogger(__name__).warning(
            "run-checks child exited with status %s; restarting (%s/%s)",
            returncode,
            restarts,
            DEFAULT_MAX_RESTARTS,
        )


def _run_streamed_child(command: list[str]) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, sys.stdout)
    selector.register(process.stderr, selectors.EVENT_READ, sys.stderr)
    output: list[str] = []
    while selector.get_map():
        for key, _ in selector.select():
            line = key.fileobj.readline()
            if line:
                if key.data is sys.stdout:
                    output.append(line)
                print(line, end="", file=key.data)
            else:
                selector.unregister(key.fileobj)
                key.fileobj.close()
    return process.wait(), "".join(output)


def _should_continue_after_summary(
    args: argparse.Namespace,
    returncode: int,
    checked: int,
) -> bool:
    if returncode != 0:
        return False
    if args.limit is None:
        return False
    return checked > 0


def _run_checks_child_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "xcube_cci_metadata_builder.cli",
        "run-checks",
        "--store-id",
        args.store_id,
        "--results-dir",
        str(args.results_dir),
        "--data-types",
        ",".join(args.data_types),
        "--timeout",
        str(args.timeout),
        "--retries",
        str(args.retries),
        "--run-once",
    ]
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    for data_id in args.data_ids or ():
        command.extend(["--data-id", data_id])
    return command


def _parse_count(output: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}:\s*(\d+)\s*$", output, re.MULTILINE)
    if match is None:
        return None
    return int(match.group(1))


def _build_descriptors(args: argparse.Namespace) -> int:
    from xcube.core.store import new_data_store

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    store = new_data_store(args.store_id)
    summary = build_descriptors(
        store=store,
        registry_dir=args.registry_dir,
        store_id=args.store_id,
        data_types=args.data_types,
        name_pattern=args.name_pattern,
        data_ids=args.data_ids,
        limit=args.limit,
    )
    print(f"described: {summary.described}")
    print(f"skipped: {summary.skipped}")
    print(f"errors: {summary.errors}")
    return 1 if summary.errors else 0


def _build_registry(args: argparse.Namespace) -> int:
    summary = build_esa_cci_registry(
        registry_dir=args.registry_dir,
        store_id=args.store_id,
    )
    print(f"entries: {summary.entries}")
    print(f"registry: {summary.output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cci-meta",
        description="Build xcube-cci-registry metadata artifacts.",
        epilog=dedent(
            """\
            common commands:
              cci-meta run-checks --results-dir work/results --limit 10
              cci-meta build-descriptors --registry-dir ../xcube-cci-registry --data-types dataset --name-pattern "LST.mon.*.v4"
              cci-meta build-registry --registry-dir ../xcube-cci-registry
              cci-meta run-checks --results-dir work/results --data-types geodataframe
              cci-meta render-states --results-dir work/results --previous-states-dir ../xcube-cci/xcube_cci/data --output-dir ../xcube-cci-registry/states
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_run_checks_parser(subparsers)
    _add_render_states_parser(subparsers)
    _add_build_descriptors_parser(subparsers)
    _add_build_registry_parser(subparsers)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
