"""Run the NXDS conformance suite with nxds_tools (the reference implementation).

    PYTHONPATH=nxds_tools/src python nxds/conformance/run.py [--update] [CASE ...]

Resolution cases: the classes of ``classes/`` and of the case are resolved
(nothing else); ``expected/<NXclass>.json`` is the resolved form of every class
the case uses. Compared (spec §15): everything except ``docs``, ``via``,
``source`` and ``provisional``, member order included.

Validation cases: ``data.h5`` (written by ``make_file.py``) is validated with the
prebuilt bundle the cases share, ``validation/bundle/`` (``index.json`` and
``resolved/``; a case may ship its own ``bundle/``). Compared: the set of
``(code, severity, path, member)`` of the E and W findings, and in partial mode
of the INCOMPLETE findings, with ``expected.jsonl``. The shared bundle must also
equal the one nxds_tools builds from ``classes/`` and every ``resolution/`` case.

``--update`` rewrites the expected files, the bundles and the HDF5 files.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from nxds_tools._build import build
from nxds_tools._build import document_json
from nxds_tools._build import format_document
from nxds_tools._build import write_bundle_directory
from nxds_tools.bundle import BundleReader
from nxds_tools.validate import validate

HERE = Path(__file__).resolve().parent
DEFINITIONS = HERE.parents[1]
SHARED = HERE / "classes"
#: keys left out of the comparison of resolved forms (spec §15)
IGNORED = ("docs", "via", "source", "provisional")
BUNDLE = "bundle"
DATA = "data.h5"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cases", nargs="*", help="case directories (default: all)")
    parser.add_argument(
        "--update", action="store_true", help="write the expected files"
    )
    args = parser.parse_args(argv)
    cases = [Path(c).resolve() for c in args.cases] or sorted(
        p
        for kind in ("resolution", "validation")
        for p in (HERE / kind).iterdir()
        if (p / "case.yaml").exists()
    )
    failures = 0
    if any(case.parent.name == "validation" for case in cases):
        problems = _shared_bundle(args.update)
        print(f"{'ok' if not problems else 'FAIL':4s} validation/{BUNDLE}")
        for problem in problems:
            print(f"     {problem}")
        failures += bool(problems)
    for case in cases:
        run = _resolution if case.parent.name == "resolution" else _validation
        problems = run(case, args.update)
        status = "ok" if not problems else "FAIL"
        print(f"{status:4s} {case.relative_to(HERE)}")
        for problem in problems:
            print(f"     {problem}")
        failures += bool(problems)
    print(f"{len(cases) - failures} passed, {failures} failed")
    return 1 if failures else 0


def _build(directories: list[Path]):
    result = build(
        DEFINITIONS, [SHARED, *directories], round_trip=False, repository=False
    )
    errors = [p.format() for p in result.report.errors]
    return result, errors


def comparable(value):
    """A resolved form without the keys §15 leaves out of the comparison."""
    if isinstance(value, dict):
        return {k: comparable(v) for k, v in value.items() if k not in IGNORED}
    if isinstance(value, list):
        return [comparable(v) for v in value]
    return value


def _resolution(case: Path, update: bool) -> list[str]:
    result, errors = _build([case])
    if errors:
        return errors
    problems = []
    expected_dir = case / "expected"
    names = sorted(result.documents)
    if update:
        expected_dir.mkdir(exist_ok=True)
        for old in expected_dir.glob("*.json"):
            old.unlink()
    for name in names:
        document = result.resolver.compact(result.documents[name])
        actual = comparable(json.loads(document_json(document)))
        expected_file = expected_dir / f"{name}.json"
        if update:
            expected_file.write_text(format_document(actual))
            continue
        if not expected_file.exists():
            problems.append(f"no {expected_file.relative_to(HERE)}")
        elif comparable(json.loads(expected_file.read_text())) != actual:
            problems.append(
                f"{name}: resolved form differs from {expected_file.relative_to(HERE)}"
            )
    if not update:
        extra = {p.name.split(".")[0] for p in expected_dir.glob("*.json")} - set(names)
        problems += [f"{name}: expected but not resolved" for name in sorted(extra)]
    return problems


def _key(finding: dict) -> tuple:
    return (finding["code"], finding["severity"], finding["path"], finding["member"])


def _bundle_problems(result, bundle: Path) -> list[str]:
    """Differences between the prebuilt bundle and a fresh build."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        write_bundle_directory(result, fresh)
        problems = []
        files = {p.relative_to(fresh) for p in fresh.rglob("*.json")}
        shipped = {p.relative_to(bundle) for p in bundle.rglob("*.json")}
        for relative in sorted(files | shipped):
            same = relative in shipped and relative in files
            if (
                not same
                or (fresh / relative).read_text() != (bundle / relative).read_text()
            ):
                problems.append(f"bundle out of date: {relative}")
        return problems


def _shared_bundle(update: bool) -> list[str]:
    """The bundle the validation cases share: ``classes/`` and every resolution case."""
    directories = sorted(
        p for p in (HERE / "resolution").iterdir() if (p / "case.yaml").exists()
    )
    result, errors = _build(directories)
    if errors:
        return errors
    bundle = HERE / "validation" / BUNDLE
    if update:
        write_bundle_directory(result, bundle)
        return []
    return _bundle_problems(result, bundle)


def _validation(case: Path, update: bool) -> list[str]:
    spec = yaml.safe_load((case / "case.yaml").read_text()) or {}
    bundle, data = case / BUNDLE, case / DATA
    if not bundle.is_dir():
        bundle = case.parent / BUNDLE
    partial = bool(spec.get("partial"))
    if update:
        data.unlink(missing_ok=True)
        subprocess.run(
            [sys.executable, str(case / "make_file.py"), str(data)],
            check=True,
            cwd=case.parent,
            env={"PYTHONPATH": str(case.parent), "PYTHONDONTWRITEBYTECODE": "1"},
        )
    problems: list[str] = []
    if not data.exists():
        return [f"no {data.relative_to(HERE)} (run with --update)"]
    with BundleReader.open(bundle) as reader:
        findings = list(
            validate(data, reader, expect=spec.get("expect"), partial=partial)
        )
    kept = [
        {"code": f.code, "severity": f.severity, "path": f.path, "member": f.member}
        for f in findings
        if f.severity in ("E", "W") or (partial and f.code == "INCOMPLETE")
    ]
    actual = sorted({_key(f) for f in kept}, key=str)
    expected_file = case / "expected.jsonl"
    if update:
        lines = [
            json.dumps(
                dict(zip(("code", "severity", "path", "member"), k, strict=True))
            )
            for k in actual
        ]
        expected_file.write_text("".join(line + "\n" for line in lines))
        return []
    expected = {
        _key(json.loads(line))
        for line in expected_file.read_text().splitlines()
        if line
    }
    problems += [
        f"missing finding {k}" for k in sorted(expected, key=str) if k not in actual
    ]
    problems += [f"unexpected finding {k}" for k in actual if k not in expected]
    return problems


if __name__ == "__main__":
    sys.exit(main())
