"""Command line: ``python -m nxds_tools {build,check,validate,docs,schema,translation-table,to-nxdl}``."""

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nxds_tools", description="NXDS prototype tools"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def phase_argument(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--phase",
            type=int,
            choices=(0, 1, 2, 3, 4),
            help="2: features NXDL cannot express (lossy) are errors",
        )

    def definitions_arguments(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--definitions", type=Path, required=True, help="definitions repository"
        )
        sub.add_argument(
            "--extra",
            type=Path,
            action="append",
            default=[],
            help="extra class directory",
        )

    build = commands.add_parser(
        "build", help="compile, resolve and write nxds/generated"
    )
    definitions_arguments(build)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument(
        "--only-extra", action="store_true", help="write only the classes of --extra"
    )
    build.add_argument("--bundle", type=Path, help="also write the bundle to this file")
    build.add_argument(
        "--legacy", type=Path, help="write generated NXDL of NXDS classes here"
    )
    build.add_argument("--docs", type=Path, help="write the documentation texts here")
    build.add_argument("--no-round-trip", action="store_true")
    phase_argument(build)

    check = commands.add_parser("check", help="compile and resolve; exit 1 on errors")
    definitions_arguments(check)
    check.add_argument("--verbose", action="store_true")
    phase_argument(check)

    validate = commands.add_parser(
        "validate", help="validate an HDF5 file with a bundle"
    )
    validate.add_argument("file", type=Path)
    validate.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="a bundle file, a generated directory (index.json + resolved/), or a "
        "catalogue directory (nxds-index.json): the bundle of the file's release",
    )
    validate.add_argument(
        "--expect", help="the application definition the file must follow"
    )
    validate.add_argument(
        "--partial", action="store_true", help="the file is still being written"
    )
    validate.add_argument("--all", action="store_true", help="also print I findings")
    validate.add_argument(
        "--json", action="store_true", help="one JSON object per finding (for tools)"
    )

    docs = commands.add_parser("docs", help="render reStructuredText for each class")
    definitions_arguments(docs)
    docs.add_argument("--out", type=Path, required=True)
    docs.add_argument(
        "--only-extra", action="store_true", help="only the classes of --extra"
    )

    schema = commands.add_parser(
        "schema",
        help="write the JSON Schemas of the models, to compare with the "
        "hand-written metaschema (nxds/metaschema)",
    )
    schema.add_argument("out", type=Path)

    table = commands.add_parser(
        "translation-table", help="the translation rows as Markdown"
    )
    table.add_argument("--out", type=Path)

    legacy = commands.add_parser(
        "legacy", help="an NXDL tree with the generated NXDL of NXDS classes"
    )
    definitions_arguments(legacy)
    legacy.add_argument("--out", type=Path, required=True)

    to_nxdl = commands.add_parser("to-nxdl", help="generate NXDL from an NXDS class")
    to_nxdl.add_argument("file", type=Path)
    definitions_arguments(to_nxdl)
    to_nxdl.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    return _COMMANDS[args.command](args)


def _build(args: argparse.Namespace) -> int:
    from ._build import build
    from ._build import write_outputs

    result = build(
        args.definitions,
        args.extra,
        round_trip=not args.no_round_trip,
        phase=args.phase,
    )
    write_outputs(
        result,
        args.out,
        only_extra=args.only_extra,
        bundle=args.bundle,
        legacy=args.legacy,
        docs=args.docs,
    )
    _summary(result)
    return 1 if result.report.errors else 0


def _summary(result) -> None:
    errors = result.report.errors
    total = sum(result.timings.values())
    warnings = sum(1 for p in result.report.problems if p.severity == "warning")
    timings = ", ".join(f"{k} {v:.1f}" for k, v in result.timings.items())
    print(
        f"{len(result.documents)} classes resolved, {len(errors)} errors, "
        f"{warnings} warnings ({total:.1f} s: {timings})",
        file=sys.stderr,
    )
    for problem in sorted(errors):
        print(problem.format(), file=sys.stderr)


def _check(args: argparse.Namespace) -> int:
    from ._build import build

    result = build(args.definitions, args.extra, phase=args.phase)
    if args.verbose:
        print(result.report.render())
    _summary(result)
    return 1 if result.report.errors else 0


def _validate(args: argparse.Namespace) -> int:
    from .bundle import CATALOGUE_FILE
    from .bundle import BundleReader
    from .bundle import select_bundle
    from .validate import file_release
    from .validate import finding_json
    from .validate import finding_text
    from .validate import validate

    errors = False
    bundle = args.bundle
    try:
        if (bundle / CATALOGUE_FILE).is_file():
            # the release attribute is in the profile of any bundle
            first, _ = select_bundle(bundle, None)
            with BundleReader.open(first) as reader:
                attribute = reader.index.profiles["hdf5"].release_attribute
            bundle, _ = select_bundle(bundle, file_release(args.file, attribute))
        for finding in validate(
            args.file, bundle, expect=args.expect, partial=args.partial
        ):
            errors = errors or finding.severity == "E"
            if args.all or finding.severity in ("E", "W"):
                print(
                    finding_json(finding) if args.json else finding_text(finding),
                    flush=True,
                )
    except BrokenPipeError:  # the reader stopped reading (``| head``)
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1 if errors else 0
    except OSError as exc:
        print(f"{args.file}: {exc}", file=sys.stderr)
        return 2
    return 1 if errors else 0


def _docs(args: argparse.Namespace) -> int:
    from ._build import build
    from .docs import write_docs

    result = build(args.definitions, args.extra, round_trip=False)
    names = None
    if args.only_extra:
        names = [n for n, item in result.files.items() if item.extra]
    write_docs(result.reader(), args.out, names)
    return 0


def _schema(args: argparse.Namespace) -> int:
    from ._build import write_schemas

    write_schemas(args.out)
    return 0


def _table(args: argparse.Namespace) -> int:
    from .translation import render_markdown

    text = render_markdown()
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")
    return 0


def _legacy(args: argparse.Namespace) -> int:
    from ._build import build
    from ._build import write_legacy_tree

    result = build(args.definitions, args.extra, round_trip=False)
    generated = write_legacy_tree(result, args.definitions, args.out)
    print(
        f"{args.out}: NXDL tree; generated {', '.join(generated) or 'nothing'}",
        file=sys.stderr,
    )
    return 1 if result.report.errors else 0


def _to_nxdl(args: argparse.Namespace) -> int:
    from ._build import build
    from .to_nxdl import legacy_nxdl
    from .to_nxdl import round_trip

    result = build(args.definitions, args.extra, round_trip=False)
    name = args.file.name.split(".")[0]
    if name not in result.documents:
        print(f"{name} is not part of the build (use --extra)", file=sys.stderr)
        return 1
    text, lossy = legacy_nxdl(name, result)
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")
    lossy, differences = round_trip(name, result)
    if lossy:
        print(f"lossy: {', '.join(lossy)}", file=sys.stderr)
    for difference in differences:
        print(f"round-trip: {difference}", file=sys.stderr)
    return 1 if differences and not lossy else 0


_COMMANDS = {
    "build": _build,
    "check": _check,
    "validate": _validate,
    "docs": _docs,
    "schema": _schema,
    "translation-table": _table,
    "to-nxdl": _to_nxdl,
    "legacy": _legacy,
}

if __name__ == "__main__":
    sys.exit(main())
