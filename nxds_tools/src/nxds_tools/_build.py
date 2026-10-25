"""Build: compile, load, resolve and write everything NXDS generates."""

import json
import shutil
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from ._report import Report
from ._xsd import XsdFacts
from ._xsd import load_facts
from .bundle import INDEX_FILE
from .bundle import BundleReader
from .bundle import write_docs_document
from .bundle import write_zip
from .model import Bundle
from .model import Catalogue
from .model import Finding
from .model import Index
from .model import ResolvedDocument
from .model import SourceClass
from .nxdl import CLASS_SPECIFIC_CLASSES
from .nxdl import compile_file
from .resolve import Resolver
from .resolve import SourceUnit
from .resolve import load_profile
from .source import load_source
from .source import write_source
from .translation import render_markdown

#: class directories of the definitions repository and their status (T17)
CLASS_DIRECTORIES = {
    "base_classes": "base",
    "applications": "application",
    "contributed_definitions": "contributed",
}
_DORMANT = ("dormant", "stagnant")
NXDL_SUFFIX = ".nxdl.xml"
NXDS_SUFFIX = ".nxds.yaml"


@dataclass
class _File:
    path: Path
    label: str
    status: str
    directory: str
    extra: bool


@dataclass
class BuildResult:
    """The outcome of a build."""

    facts: XsdFacts
    release: str
    units: dict[str, SourceUnit]
    documents: dict[str, ResolvedDocument]
    resolver: Resolver
    report: Report
    files: dict[str, _File] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    lossy: dict[str, list[str]] = field(default_factory=dict)

    def bundle(self) -> Bundle:
        """The bundle: index and compact documents, without documentation."""
        return self.resolver.bundle(self.release, self.documents)

    def reader(self) -> BundleReader:
        """A reader of the bundle, with documentation texts."""
        return BundleReader.from_bundle(self.bundle(), self.resolver.docs)


def _status(relative: Path, default: str) -> str:
    if any(part.startswith(_DORMANT) for part in relative.parts[:-1]):
        return "dormant"
    return (
        CLASS_DIRECTORIES.get(relative.parts[0], default) if relative.parts else default
    )


def _discover(
    definitions: Path, extra: list[Path], repository: bool = True
) -> list[_File]:
    files = []
    for directory in CLASS_DIRECTORIES if repository else ():
        root = definitions / directory
        for path in sorted(root.rglob("*")):
            if (
                path.name.endswith((NXDL_SUFFIX, NXDS_SUFFIX))
                and "nyaml" not in path.parts
            ):
                relative = path.relative_to(definitions)
                files.append(
                    _File(
                        path,
                        str(relative),
                        _status(relative, "contributed"),
                        directory,
                        False,
                    )
                )
    for root in extra:
        for path in sorted(root.rglob("*")):
            if "generated" in path.relative_to(root).parts:
                continue
            if path.name.endswith((NXDL_SUFFIX, NXDS_SUFFIX)):
                label = str(path.relative_to(root.parent))
                files.append(_File(path, label, "local", root.name, True))
    return files


def read_release(definitions: Path) -> str:
    """The release the definitions directory declares (``NXDL_VERSION``)."""
    version_file = definitions / "NXDL_VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


def load_units(
    definitions: Path,
    extra: list[Path],
    facts: XsdFacts,
    report: Report,
    repository: bool = True,
) -> tuple[dict[str, SourceUnit], dict[str, _File]]:
    """Compile NXDL files and load NXDS files; one source per class."""
    units: dict[str, SourceUnit] = {}
    files: dict[str, _File] = {}
    for item in _discover(definitions, extra, repository):
        name = item.path.name.split(".")[0]
        if name in files:
            report.error(
                "duplicate-class",
                f"class {name} also defined in {files[name].label} (one source per class)",
                item.label,
            )
            continue
        if item.path.name.endswith(NXDL_SUFFIX):
            compiled = compile_file(item.path, item.label, facts, report)
            origin = "nxdl"
        else:
            compiled = load_source(item.path, item.label, report)
            origin = "nxds"
        if compiled is None:
            continue
        units[name] = SourceUnit(compiled=compiled, status=item.status, origin=origin)
        files[name] = item
    return units, files


def build(
    definitions: Path,
    extra: list[Path] | None = None,
    round_trip: bool = True,
    phase: int | None = None,
    repository: bool = True,
) -> BuildResult:
    """Compile and resolve every class of a definitions directory (and extra directories).

    With ``phase=2``, an NXDS class that NXDL cannot express, or that a
    class-specific translation row covers, is an error.
    """
    timings: dict[str, float] = {}
    start = time.perf_counter()
    report = Report()
    facts = load_facts(definitions)
    timings["xsd"] = time.perf_counter() - start
    start = time.perf_counter()
    units, files = load_units(definitions, list(extra or []), facts, report, repository)
    timings["compile"] = time.perf_counter() - start
    start = time.perf_counter()
    resolver = Resolver(units, facts, load_profile(facts), report)
    documents = resolver.resolve_all()
    timings["resolve"] = time.perf_counter() - start
    result = BuildResult(
        facts=facts,
        release=read_release(definitions),
        units=units,
        documents=documents,
        resolver=resolver,
        report=report,
        files=files,
        timings=timings,
    )
    if round_trip:
        start = time.perf_counter()
        _round_trips(result, phase)
        timings["round-trip"] = time.perf_counter() - start
    return result


def _round_trips(result: BuildResult, phase: int | None) -> None:
    from .to_nxdl import round_trip

    strict = phase == 2
    for name, unit in sorted(result.units.items()):
        if unit.origin != "nxds" or name not in result.documents:
            continue
        if strict and name in CLASS_SPECIFIC_CLASSES:
            result.report.error(
                "phase-2",
                f"{name} has class-specific translation rows (T13): it stays NXDL until phase 4",
                unit.compiled.file,
            )
        lossy, differences = round_trip(name, result)
        result.lossy[name] = lossy
        if lossy:
            result.documents[name].definition.lossy = lossy
            result.report.add(
                "error" if strict else "info",
                "lossy",
                f"generated NXDL loses {', '.join(lossy)}"
                + (
                    " (phase 2: NXDS classes may only use what NXDL can express)"
                    if strict
                    else ""
                ),
                unit.compiled.file,
            )
        for difference in differences:
            severity = "info" if lossy else "error"
            result.report.add(severity, "round-trip", difference, unit.compiled.file)
        if not differences:
            result.report.info(
                "round-trip-ok",
                "NXDS → NXDL → NXDS gives the same resolved form",
                unit.compiled.file,
            )


def dump_json(data: dict) -> str:
    """Canonical JSON: sorted keys, stable indentation."""
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def document_json(document: ResolvedDocument) -> str:
    """One class per file, one member per line, empty lists left out."""
    data = document.model_dump(by_alias=True, exclude_none=True, mode="json")
    for group in [data["definition"], *data["specialisations"].values()]:
        for key in ("children", "attributes"):
            for member in group.get(key, []):
                _drop_empty(member)
    return format_document(data)


def _drop_empty(member: dict) -> None:
    for attribute in member.get("attributes", []):
        _drop_empty(attribute)
    for key in ("docs", "refined_by", "attributes", "provisional", "via"):
        if member.get(key) == []:
            del member[key]
    if member.get("shape", {}).get("symbols") == {}:
        del member["shape"]["symbols"]


def compact_json(data: dict) -> str:
    """Canonical JSON without whitespace (sorted keys)."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def format_document(data: dict) -> str:
    """Pretty JSON where every member is one line, so diffs show members."""

    def members(items: list, indent: str) -> str:
        if not items:
            return "[]"
        lines = [
            indent + "  " + json.dumps(m, sort_keys=True, ensure_ascii=False)
            for m in items
        ]
        return "[\n" + ",\n".join(lines) + "\n" + indent + "]"

    def group(value: dict, indent: str) -> str:
        parts = []
        for key in sorted(value):
            item = value[key]
            if key in ("children", "attributes"):
                text = members(item, indent + " ")
            else:
                text = json.dumps(item, sort_keys=True, ensure_ascii=False)
            parts.append(f"{indent} {json.dumps(key)}: {text}")
        return "{\n" + ",\n".join(parts) + "\n" + indent + "}"

    parts = []
    for key in sorted(data):
        if key == "definition":
            text = group(data[key], " ")
        elif key == "specialisations":
            inner = [
                f"  {json.dumps(k)}: {group(v, '  ')}"
                for k, v in sorted(data[key].items())
            ]
            text = "{\n" + ",\n".join(inner) + "\n }" if inner else "{}"
        else:
            text = json.dumps(data[key])
        parts.append(f" {json.dumps(key)}: {text}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


#: the models of the files the hand-written metaschema (``nxds/metaschema``) describes
METASCHEMA = {
    "source": SourceClass,
    "resolved": ResolvedDocument,
    "index": Index,
    "finding": Finding,
    "catalogue": Catalogue,
}


def metaschema() -> dict[str, str]:
    """The JSON Schemas of the models, by file name (``source.json``, …)."""
    texts = {}
    for name, model in METASCHEMA.items():
        schema = model.model_json_schema(by_alias=True)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"{name}.json"
        texts[f"{name}.json"] = dump_json(schema)
    return texts


def write_schemas(out: Path) -> None:
    """Write the JSON Schemas of the models (for comparison with the metaschema)."""
    out.mkdir(parents=True, exist_ok=True)
    for name, text in metaschema().items():
        (out / name).write_text(text)


def write_bundle_directory(result: BuildResult, out: Path) -> None:
    """A bundle as a directory a validator reads lazily: ``index.json`` and
    ``resolved/<NXclass>.json`` (spec §15)."""
    if (out / "resolved").exists():
        shutil.rmtree(out / "resolved")
    (out / "resolved").mkdir(parents=True)
    index = result.resolver.index(result.release, result.documents)
    (out / INDEX_FILE).write_text(
        dump_json(index.model_dump(by_alias=True, exclude_none=True, mode="json"))
    )
    for name, document in sorted(result.documents.items()):
        (out / "resolved" / f"{name}.json").write_text(
            document_json(result.resolver.compact(document))
        )


def write_outputs(
    result: BuildResult,
    out: Path,
    only_extra: bool = False,
    bundle: Path | None = None,
    legacy: Path | None = None,
    docs: Path | None = None,
) -> None:
    """Write source/, resolved/, index.json, translation.md and report.txt."""
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("source", "resolved"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
    for name, unit in sorted(result.units.items()):
        item = result.files[name]
        if only_extra and not item.extra:
            continue
        if unit.origin == "nxdl":
            directory = (
                out / "source" if item.extra else out / "source" / item.directory
            )
            write_source(unit.compiled.source, directory / f"{name}.nxds.yaml")
        document = result.documents.get(name)
        if document is not None:
            path = out / "resolved" / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(document_json(result.resolver.compact(document)))
        if docs is not None and name in result.resolver.docs:
            write_docs_document(result.resolver.docs[name], docs / f"{name}.json")
    if not only_extra:
        index = result.resolver.index(result.release, result.documents)
        (out / INDEX_FILE).write_text(
            dump_json(index.model_dump(by_alias=True, exclude_none=True, mode="json"))
        )
        if (out / "schema").exists():
            shutil.rmtree(out / "schema")  # the metaschema lives in nxds/metaschema
        (out / "translation.md").write_text(render_markdown())
    report = result.report
    if only_extra:
        labels = {item.label for item in result.files.values() if item.extra}
        report = Report([p for p in report.problems if p.file in labels])
    (out / "report.txt").write_text(report.render())
    if legacy is not None:
        from .to_nxdl import legacy_nxdl

        for name, unit in sorted(result.units.items()):
            if (
                unit.origin == "nxds"
                and name in result.documents
                and not (only_extra and not result.files[name].extra)
            ):
                text, _ = legacy_nxdl(name, result)
                legacy.mkdir(parents=True, exist_ok=True)
                (legacy / f"{name}.nxdl.xml").write_text(text)
    if bundle is not None and bundle.suffix == ".zip":
        resolver = result.resolver
        write_zip(
            bundle,
            resolver.index(result.release, result.documents),
            {n: resolver.compact(d) for n, d in result.documents.items()},
            resolver.docs,
        )
    elif bundle is not None:
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text(
            compact_json(
                result.bundle().model_dump(
                    by_alias=True, exclude_none=True, mode="json"
                )
            )
        )


def write_legacy_tree(result: BuildResult, definitions: Path, out: Path) -> list[str]:
    """An NXDL tree for tools that read only NXDL: the repository's NXDL files
    (linked) and the generated NXDL of every NXDS class; returns those classes."""
    from .to_nxdl import legacy_nxdl

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for path in sorted(definitions.iterdir()):
        if path.is_file() and path.suffix in (".xsd",) or path.name == "NXDL_VERSION":
            (out / path.name).symlink_to(path.resolve())
    for directory in CLASS_DIRECTORIES:
        source = definitions / directory
        if not source.is_dir():
            continue
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if (
                path.is_dir()
                or path.name.endswith(NXDS_SUFFIX)
                or "nyaml" in relative.parts
            ):
                continue
            target = out / directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(path.resolve())
    generated = []
    for name, unit in sorted(result.units.items()):
        item = result.files[name]
        if unit.origin != "nxds" or item.extra or name not in result.documents:
            continue
        text, _ = legacy_nxdl(name, result)
        relative = item.path.relative_to(definitions / item.directory)
        target = out / item.directory / relative.parent / f"{name}{NXDL_SUFFIX}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            _LEGACY_HEADER.format(source=item.label) + text.split("\n", 1)[1]
        )
        generated.append(name)
    return generated


_LEGACY_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="nxdlformat.xsl" ?>
<!-- Generated by nxds_tools from {source}: do not edit. -->
"""
