"""NXDS source form → NXDL, for the legacy artifact and the round-trip check."""

from collections.abc import Callable
from typing import TYPE_CHECKING

import lxml.etree as ET

from ._report import Report
from .model import AnyName
from .model import DimExpr
from .model import ExactName
from .model import OptionalDim
from .model import RefName
from .model import ResolvedChild
from .model import SourceAttribute
from .model import SourceChild
from .model import SourceClass
from .model import TemplateName
from .model import UndeclaredPerKind
from .model import UnitsCategory
from .nxdl import CompiledClass
from .nxdl import compile_file
from .nxdl import t2_id
from .nxdl import template_of

if TYPE_CHECKING:
    from ._build import BuildResult

_NS = "http://definition.nexusformat.org/nxdl/3.1"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_ELEMENT_OF_NODE = {"group": "group", "dataset": "field", "link": "link"}

#: (id path, node kind or None) → the resolved member it reaches
TargetLookup = Callable[[str, str | None], ResolvedChild | None]


def to_nxdl(
    source: SourceClass,
    lookup: TargetLookup | None = None,
    nxdl_type_default: str = "NX_CHAR",
) -> tuple[str, list[str]]:
    """The NXDL text of a source form, and the features NXDL cannot express."""
    writer = _Writer(source, lookup, nxdl_type_default)
    return writer.write(), sorted(writer.lossy)


def legacy_nxdl(name: str, result: "BuildResult") -> tuple[str, list[str]]:
    """The generated NXDL of a class of a build, and what it loses."""
    unit = result.units[name]
    original = result.documents[name]
    resolver = result.resolver

    def lookup(path: str, node: str | None = None) -> ResolvedChild | None:
        return resolver.resolve_target(original.definition, path, node)

    return to_nxdl(
        unit.compiled.source, lookup, result.facts.default("field", "type") or "NX_CHAR"
    )


def round_trip(name: str, result: "BuildResult") -> tuple[list[str], list[str]]:
    """Generate NXDL from an NXDS class, compile it back and compare resolved forms."""
    from .resolve import Resolver
    from .resolve import SourceUnit
    from .resolve import load_profile

    unit = result.units[name]
    original = result.documents[name]
    text, lossy = legacy_nxdl(name, result)
    report = Report()
    root = ET.fromstring(text.encode())
    compiled = _compile_tree(root, unit.compiled.file, result, report)
    if compiled is None:
        return lossy, [p.format() for p in report.problems]
    units = dict(result.units)
    units[name] = SourceUnit(compiled=compiled, status=unit.status, origin="nxdl")
    again = Resolver(units, result.facts, load_profile(result.facts), report)
    resolved = again.resolve(name)
    if resolved is None:
        return lossy, ["generated NXDL does not resolve"]
    specs = again.specialisations_of(name)
    before = _comparable(
        {"definition": original.definition, "specialisations": original.specialisations}
    )
    after = _comparable({"definition": resolved, "specialisations": specs})
    before["docs"] = result.resolver.docs.get(name, {})
    after["docs"] = again.docs.get(name, {})
    differences = list(_diff(before, after, ""))
    return lossy, differences[:20]


def _compile_tree(
    root: ET._Element, label: str, result: "BuildResult", report: Report
) -> CompiledClass | None:
    import tempfile
    from pathlib import Path

    name = root.get("name")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}.nxdl.xml"
        path.write_bytes(ET.tostring(root))
        return compile_file(path, f"{name}.nxdl.xml", result.facts, report)


_IGNORED = {"via", "provisional", "source", "lossy"}


def _comparable(document: dict) -> dict:
    data = {
        "definition": document["definition"].model_dump(
            by_alias=True, exclude_none=True, mode="json"
        ),
        "specialisations": {
            k: v.model_dump(by_alias=True, exclude_none=True, mode="json")
            for k, v in document["specialisations"].items()
        },
    }
    return _strip(data)


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _IGNORED}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _diff(before, after, path: str):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            if key not in after:
                yield f"{path}/{key}: only in the NXDS class"
            elif key not in before:
                yield f"{path}/{key}: only in the generated NXDL"
            else:
                yield from _diff(before[key], after[key], f"{path}/{key}")
    elif (
        isinstance(before, list)
        and isinstance(after, list)
        and len(before) == len(after)
    ):
        for index, (b, a) in enumerate(zip(before, after, strict=True)):
            label = b.get("id", index) if isinstance(b, dict) else index
            yield from _diff(b, a, f"{path}[{label}]")
    elif before != after:
        yield f"{path}: {before!r} != {after!r}"


def _with_constraints(doc: str | None, require: list) -> str:
    """Documentation that states the constraints NXDL cannot express."""
    from .model import constraint_kind

    lines = [doc] if doc else []
    for constraint in require:
        kind, members = constraint_kind(constraint)
        lines.append(
            f"NXDS constraint (not checked by NXDL tools): {kind.replace('_', ' ')}: {', '.join(members)}."
        )
    return "\n\n".join(lines)


class _Writer:
    def __init__(
        self, source: SourceClass, lookup: TargetLookup | None, type_default: str
    ) -> None:
        self._source = source
        self._lookup = lookup
        self._type_default = type_default
        self._application = source.category == "application"
        self.lossy: set[str] = set()

    def _sub(self, parent: ET._Element, tag: str, **attributes: str) -> ET._Element:
        element = ET.SubElement(parent, f"{{{_NS}}}{tag}")
        for key, value in attributes.items():
            if value is not None:
                element.set(key, value)
        return element

    def _doc(self, parent: ET._Element, text: str | None) -> None:
        if text:
            # NXDL convention: the text on its own lines, indented below <doc>
            depth = sum(1 for _ in parent.iterancestors()) + 1
            inner = "  " * (depth + 1)
            lines = [inner + line if line else "" for line in text.splitlines()]
            doc = self._sub(parent, "doc")
            doc.text = "\n" + "\n".join(lines) + "\n" + "  " * depth

    def write(self) -> str:
        source = self._source
        defaults = source.defaults
        if (
            defaults.min != (1 if self._application else 0)
            or defaults.binding != self._application
        ):
            self.lossy.add("defaults")
        if defaults.type not in (None, self._type_default):
            self.lossy.add("defaults.type")
        root = ET.Element(f"{{{_NS}}}definition", nsmap={None: _NS, "xsi": _XSI})
        root.set("name", source.class_)
        root.set("extends", source.extends or "NXobject")
        root.set("type", "group")
        root.set("category", source.category)
        root.set(f"{{{_XSI}}}schemaLocation", f"{_NS} ../nxdl.xsd")
        if source.deprecated:
            root.set("deprecated", source.deprecated)
        undeclared = source.undeclared
        if undeclared is not None:
            if isinstance(undeclared, str):
                undeclared = UndeclaredPerKind(
                    group=undeclared, dataset=undeclared, attribute=undeclared
                )
            for kind, flag in (
                ("group", "ignoreExtraGroups"),
                ("dataset", "ignoreExtraFields"),
                ("attribute", "ignoreExtraAttributes"),
            ):
                policy = getattr(undeclared, kind)
                if policy == "ignore":
                    root.set(flag, "true")
                elif policy == "error":
                    self.lossy.add("undeclared.error")
        if source.symbols:
            symbols = self._sub(root, "symbols")
            for name, symbol in source.symbols.items():
                element = self._sub(symbols, "symbol", name=name)
                self._doc(element, symbol.doc)
        self._doc(
            root,
            (
                _with_constraints(source.doc, source.require)
                if source.require
                else source.doc
            ),
        )
        if source.require:
            self.lossy.add("require")
        self._content(root, source.attributes, source.children)
        ET.indent(root, space="  ")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(root, encoding="unicode")
            + "\n"
        )

    def _content(
        self,
        parent: ET._Element,
        attributes: dict[str, SourceAttribute],
        children: dict[str, SourceChild],
        path: tuple[str, ...] = (),
    ) -> None:
        for key, member in attributes.items():
            self._member(parent, key, member, "attribute", path)
        for key, member in children.items():
            self._member(
                parent, member.id or key, member, _ELEMENT_OF_NODE[member.node], path
            )

    def _inherited_role(self, path: tuple[str, ...], name: RefName) -> bool:
        """Whether a role refines a role the class inherits (so NXDL can name it)."""
        if self._lookup is None:
            return False
        member = self._lookup("/".join(path), "dataset")
        return (
            member is not None
            and member.name == name
            and member.declared_by != self._source.class_
        )

    def _naming(
        self,
        element: ET._Element,
        member_id: str,
        member,
        tag: str,
        path: tuple[str, ...],
    ) -> None:
        name = member.name or ExactName(exact=member_id)
        if isinstance(name, RefName):
            if tag != "field" or not self._inherited_role((*path, member_id), name):
                self.lossy.add("name.ref")
            element.set("name", member_id)
            element.set("nameType", "any")
        elif isinstance(name, TemplateName):
            plain = name.template.replace("{", "").replace("}", "")
            if plain != member_id or template_of(plain) != name.template:
                self.lossy.add("name.template")
            element.set("name", plain)
            element.set("nameType", "partial")
        elif isinstance(name, AnyName):
            if tag == "group" and member_id == t2_id(member.class_ or ""):
                return
            element.set("name", member_id)
            element.set("nameType", "any")
        else:
            if name.exact != member_id:
                self.lossy.add("name.exact")
            element.set("name", name.exact)
            if any(c.isupper() for c in name.exact):
                element.set("nameType", "specified")

    def _member(
        self,
        parent: ET._Element,
        member_id: str,
        member,
        tag: str,
        path: tuple[str, ...],
    ) -> None:
        element = self._sub(parent, tag)
        if tag == "group":
            element.set("type", member.class_ or "")
        self._naming(element, member_id, member, tag, path)
        # NXDL attribute order is cosmetic; occurrence first
        occurs = member.occurs
        if tag in ("group", "field"):
            if occurs is not None and occurs.min is not None:
                element.set("minOccurs", str(occurs.min))
            if occurs is not None and occurs.max is not None:
                element.set("maxOccurs", str(occurs.max))
        elif tag == "attribute":
            if occurs is not None and occurs.min is not None:
                if occurs.min > 1:
                    self.lossy.add("occurs")
                element.set("optional", "true" if occurs.min == 0 else "false")
            if occurs is not None and occurs.max not in (None, 1):
                self.lossy.add("occurs")
        elif occurs is not None and (
            occurs.min not in (None, self._source.defaults.min)
            or occurs.max is not None
        ):
            self.lossy.add("link.occurs")
        if member.recommended:
            element.set("recommended", "true")
        if member.deprecated:
            element.set("deprecated", member.deprecated)
        if member.type is not None and tag in ("field", "attribute"):
            element.set("type", member.type)
        if tag == "field" and member.units is not None:
            element.set(
                "units",
                (
                    member.units.category
                    if isinstance(member.units, UnitsCategory)
                    else member.units.fixed
                ),
            )
        if tag == "attribute" and member.units is not None:
            self.lossy.add("units.attribute")
        for key in ("length", "rank", "names_child"):
            if getattr(member, key) is not None:
                self.lossy.add(key)
        if member.show:
            self.lossy.add("show")
        if tag == "link":
            element.set("target", self._target(member.target or ""))
        doc = member.doc
        if isinstance(member, SourceChild) and member.require:
            doc = _with_constraints(doc, member.require)
        self._doc(element, doc)
        if member.shape is not None:
            self._dimensions(element, member.shape)
        if member.enum is not None:
            enumeration = self._sub(element, "enumeration")
            if member.enum.open:
                enumeration.set("open", "true")
            for value in member.enum.values:
                text = value.value
                if isinstance(text, list):
                    text = " ".join(str(v) for v in text)
                elif isinstance(text, bool):
                    text = "true" if text else "false"
                item = self._sub(enumeration, "item", value=str(text))
                if value.deprecated:
                    self.lossy.add("enum.deprecated")
                self._doc(item, value.doc)
        if isinstance(member, SourceChild):
            if member.require:
                self.lossy.add("require")
            if member.undeclared is not None:
                self.lossy.add("undeclared")
            if tag == "link" and member.attributes:
                self.lossy.add("link.attributes")
            self._content(
                element,
                member.attributes,
                member.children if tag == "group" else {},
                (*path, member_id),
            )

    def _dimensions(self, element: ET._Element, shape) -> None:
        if shape.binding is not None and shape.binding != self._source.defaults.binding:
            self.lossy.add("shape.binding")
        dimensions = self._sub(element, "dimensions")
        dims = shape.dims or []
        rank = (
            shape.rank
            if shape.rank is not None
            else (len(dims) if shape.dims is not None else None)
        )
        if isinstance(rank, DimExpr):
            dimensions.set("rank", rank.expr)
        elif rank is not None:
            dimensions.set("rank", str(rank))
        for index, dim in enumerate(dims, start=1):
            if dim is None:
                continue
            item = self._sub(dimensions, "dim", index=str(index))
            if isinstance(dim, OptionalDim):
                item.set("required", "false")
                dim = dim.value
                if dim is None:
                    continue
            item.set("value", dim.expr if isinstance(dim, DimExpr) else str(dim))

    def _target(self, target: str) -> str:
        if target.startswith("/"):
            if self._application:
                self.lossy.add("target")
            target = target[1:]
        steps = target.split("/")
        parts = []
        for index in range(len(steps)):
            if index == len(steps) - 1:
                parts.append(steps[index])
                break
            member = (
                self._lookup("/".join(steps[: index + 1]), "group")
                if self._lookup
                else None
            )
            if member is None or member.node != "group" or not member.class_:
                self.lossy.add("target")
                parts.append(steps[index])
            elif isinstance(member.name, AnyName) and member.id == t2_id(member.class_):
                parts.append(member.class_)
            else:
                parts.append(f"{member.id}:{member.class_}")
        return "/" + "/".join(parts)
