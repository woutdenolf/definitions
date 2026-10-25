"""NXDL → NXDS source form: the compiler implementing the translation rows."""

import inspect
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import lxml.etree as ET

from ._report import Report
from ._xsd import XsdFacts
from .model import AnyName
from .model import AtMostOneOf
from .model import Constraint
from .model import Defaults
from .model import DimExpr
from .model import Enumeration
from .model import EnumValue
from .model import ExactlyOneOf
from .model import ExactName
from .model import Name
from .model import Occurs
from .model import OptionalDim
from .model import RefName
from .model import Shape
from .model import SourceAttribute
from .model import SourceChild
from .model import SourceClass
from .model import Symbol
from .model import TemplateName
from .model import TypeDef
from .model import UndeclaredPerKind
from .model import UnitsCategory
from .model import UnitsFixed
from .translation import provisional_for
from .translation import sort_rows

#: the class every base class extends, and the class an application describes (T8)
OBJECT_CLASS = "NXobject"
ROOT_CLASS = "NXroot"

#: classes that class-specific translation rows (T13) cover
CLASS_SPECIFIC_CLASSES = ("NXdata", OBJECT_CLASS)
_NODE_OF_ELEMENT = {"group": "group", "field": "dataset", "link": "link"}
_LEGACY_FIELD_ATTRIBUTES = (
    "signal",
    "axis",
    "primary",
    "axes",
    "long_name",
    "interpretation",
)
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_INTEGER = re.compile(r"[+-]?\d+")
_EXPRESSION = re.compile(r"[\w\s+\-*]+")
_UPPER_RUN = re.compile(r"[A-Z]+")


@dataclass
class CompiledClass:
    """A source form with the line of each member in the NXDL file."""

    source: SourceClass
    file: str
    #: id path (attributes as ``@id``) → line in the file
    lines: dict[tuple[str, ...], int] = field(default_factory=dict)


def compile_file(
    path: Path, label: str, facts: XsdFacts, report: Report
) -> CompiledClass | None:
    """Translate one ``*.nxdl.xml`` file; problems go to the report."""
    try:
        tree = ET.parse(str(path))
    except (OSError, ET.XMLSyntaxError) as exc:
        report.error("xml", f"cannot parse: {exc}", label)
        return None
    compiler = _Compiler(facts, report, label)
    try:
        return compiler.definition(tree.getroot())
    except Exception as exc:  # a compiler bug must not stop the build
        first = str(exc).splitlines()[0] if str(exc) else ""
        report.error("compiler-crash", f"{type(exc).__name__}: {first}", label)
        return None


def t2_id(nx_class: str) -> str:
    """The id of an unnamed group: the class without ``NX``, in upper case (T2)."""
    return nx_class[2:].upper() if nx_class.startswith("NX") else nx_class.upper()


def template_of(name: str) -> str:
    """``AXISNAME_indices`` → ``{AXISNAME}_indices`` (T3)."""
    return _UPPER_RUN.sub(lambda m: "{" + m.group(0) + "}", name)


def target_to_ids(target: str, absolute: bool = False) -> str:
    """``/NXentry/NXinstrument/mono:NXmonochromator/energy`` → ``ENTRY/INSTRUMENT/mono/energy``
    (T10); ``absolute``: a label path from the root class (``/ENTRY/…``, base classes).
    """
    steps = []
    for step in target.strip("/").split("/"):
        if ":" in step:
            steps.append(step.split(":", 1)[0])
        elif step.startswith("NX") and len(step) > 2:
            steps.append(t2_id(step))
        else:
            steps.append(step)
    return ("/" if absolute else "") + "/".join(steps)


def expression_of(text: str) -> str:
    """A dimension expression in NXDS syntax: ``2n`` → ``2*n``, no spaces (T9b)."""
    return re.sub(r"(\d)([A-Za-z_])", r"\1*\2", re.sub(r"\s+", "", text))


def typed_enum(
    enum: Enumeration, type_name: str | None, shape, types: dict[str, TypeDef]
) -> tuple[Enumeration, list[str]]:
    """Enumeration values written as text, typed with the member's resolved type
    and shape (§5.2.7): numbers parsed; for an array-shaped member a text value
    with spaces (``". ."``) or a numeric ``[0, 0, 1]`` becomes a list. Also the
    values that do not parse."""
    array = shape is not None and (
        (isinstance(shape.rank, int) and shape.rank > 0)
        or not isinstance(shape.rank, int | None)
        or bool(shape.dims)
    )
    kinds: set[str] = set()
    _value_kinds(type_name, types, kinds)
    bad: list[str] = []

    def one(text):
        if not isinstance(text, str) or type_name is None:
            return text
        try:
            if kinds == {"int"}:
                return int(text)
            if kinds <= {"int", "float"} and kinds:
                number = float(text)
                if "int" in kinds and _INTEGER.fullmatch(text.strip()):
                    return int(number)
                return number
            if kinds == {"bool"}:
                if text.strip() in ("true", "1"):
                    return True
                if text.strip() in ("false", "0"):
                    return False
                raise ValueError(text)
        except ValueError:
            bad.append(text)
        return text

    values = []
    for item in enum.values:
        value = item.value
        if (
            isinstance(value, str)
            and array
            and kinds == {"str"}
            and len(value.split()) > 1
        ):
            value = [one(part) for part in value.split()]
        elif (
            isinstance(value, str)
            and array
            and kinds
            and kinds <= {"int", "float"}
            and value.strip().startswith("[")
            and value.strip().endswith("]")
        ):
            # a numeric array written as a list: [0, 0, 1]
            parts = value.strip()[1:-1].replace(",", " ").split()
            value = [one(part) for part in parts]
        elif isinstance(value, list):
            value = [one(part) for part in value]
        else:
            value = one(value)
        values.append(item.model_copy(update={"value": value}))
    return enum.model_copy(update={"values": values}), bad


def _value_kinds(type_name: str | None, types: dict[str, TypeDef], kinds: set[str]):
    type_def = types.get(type_name or "")
    if type_def is None:
        kinds.add("str")
        return
    if type_def.variety == "union":
        for member in type_def.members:
            _value_kinds(member, types, kinds)
        return
    if type_def.variety == "list":
        kinds.add("str")
        return
    builtins = type_def.builtins
    if "xs:integer" in builtins:
        kinds.add("int")
    elif "xs:float" in builtins or "xs:double" in builtins or "xs:decimal" in builtins:
        kinds.add("float")
    elif "xs:boolean" in builtins:
        kinds.add("bool")
    else:
        kinds.add("str")


def _local(element: ET._Element) -> str:
    return ET.QName(element).localname


def _doc_text(element: ET._Element) -> str | None:
    for child in element:
        if isinstance(child.tag, str) and _local(child) == "doc":
            text = inspect.cleandoc("".join(child.itertext()))
            return text or None
    return None


class _Compiler:
    def __init__(self, facts: XsdFacts, report: Report, label: str) -> None:
        self._facts = facts
        self._report = report
        self._label = label
        self._lines: dict[tuple[str, ...], int] = {}
        self._application = False
        self._name_re = re.compile(facts.names.item_pattern) if facts.names else None
        self._class_re = re.compile(facts.names.class_pattern) if facts.names else None
        self._target_re = (
            re.compile(facts.names.target_pattern)
            if facts.names and facts.names.target_pattern
            else None
        )

    # ---------------------------------------------------------------- helpers

    def _warn(self, code: str, message: str, element: ET._Element | None) -> None:
        self._report.warning(
            code,
            message,
            self._label,
            element.sourceline if element is not None else None,
        )

    def _error(self, code: str, message: str, element: ET._Element | None) -> None:
        self._report.error(
            code,
            message,
            self._label,
            element.sourceline if element is not None else None,
        )

    def _bool(self, element: ET._Element, attribute: str) -> bool | None:
        value = element.get(attribute)
        if value is None:
            return None
        text = value.strip()
        if text in ("true", "1"):
            return True
        if text in ("false", "0"):
            return False
        self._error(
            "bad-boolean", f"{attribute}={value!r} is not an xs:boolean", element
        )
        return None

    def _check_attributes(self, element: ET._Element, tag: str) -> None:
        known = self._facts.attributes.get(tag, {})
        for attribute in element.attrib:
            if attribute.startswith("{"):
                continue
            if attribute not in known and attribute not in ("reused_from", "valueFrom"):
                self._warn(
                    "unknown-xml-attribute",
                    f"<{tag}> has unknown attribute {attribute!r}",
                    element,
                )

    def _check_name(self, name: str, element: ET._Element) -> None:
        names = self._facts.names
        if names is None or self._name_re is None:
            return
        if not self._name_re.fullmatch(name):
            self._error(
                "invalid-name",
                f"name {name!r} does not match the name grammar",
                element,
            )
        elif names.item_max_length is not None and len(name) > names.item_max_length:
            self._error(
                "invalid-name",
                f"name {name!r} is longer than {names.item_max_length}",
                element,
            )

    # ------------------------------------------------------------- definition

    def definition(self, root: ET._Element) -> CompiledClass:
        self._check_attributes(root, "definition")
        name = root.get("name") or ""
        category = root.get("category")
        if category not in ("base", "application"):
            self._error("bad-category", f"category {category!r}", root)
            category = "base"
        self._application = category == "application"
        stem = Path(self._label).name.split(".")[0]
        if name != stem:
            self._error("name-mismatch", f"class {name!r} in file {stem!r}", root)
        via = []
        extends = root.get("extends")
        describes = None
        if self._application:
            describes = ROOT_CLASS
            if extends in (None, OBJECT_CLASS):
                extends = None
            via.append("T8")
        elif extends is None and name != OBJECT_CLASS:
            extends = OBJECT_CLASS
            via.append("T8")
        if root.get("restricts") is not None:
            self._warn("unsupported", "restricts is ignored", root)

        field_type = self._facts.default("field", "type")
        attribute_type = self._facts.default("attribute", "type")
        if field_type != attribute_type:
            self._warn(
                "xsd", "field/@type and attribute/@type have different defaults", root
            )
        defaults = Defaults(
            min=1 if self._application else 0,
            binding=self._application,
            type=field_type,
        )

        undeclared = None
        flags = {
            "group": "ignoreExtraGroups",
            "dataset": "ignoreExtraFields",
            "attribute": "ignoreExtraAttributes",
        }
        policy = {
            kind: "ignore" if self._bool(root, flag) else "report"
            for kind, flag in flags.items()
        }
        if any(value == "ignore" for value in policy.values()):
            undeclared = UndeclaredPerKind(**policy)
            via.append("T12")

        symbols: dict[str, Symbol] = {}
        for child in root:
            if isinstance(child.tag, str) and _local(child) == "symbols":
                for symbol in child:
                    if not isinstance(symbol.tag, str) or _local(symbol) != "symbol":
                        continue
                    symbol_name = symbol.get("name")
                    if not symbol_name:
                        self._warn("symbol-without-name", "symbol without name", symbol)
                        continue
                    if symbol_name in symbols:
                        self._warn(
                            "duplicate-symbol",
                            f"symbol {symbol_name!r} declared twice",
                            symbol,
                        )
                    symbols[symbol_name] = Symbol(doc=_doc_text(symbol))

        attributes, children, require = self._content(root, ())
        source = SourceClass(
            class_=name,
            category=category,
            extends=extends,
            describes=describes,
            deprecated=root.get("deprecated"),
            doc=_doc_text(root),
            defaults=defaults,
            symbols=symbols,
            attributes=attributes,
            children=children,
            require=require,
            undeclared=undeclared,
            via=via or None,
            provisional=provisional_for(via) or None,
        )
        self._class_specific(source)
        self._check_free_names(root, source.attributes, source.children)
        self._lines[()] = root.sourceline
        return CompiledClass(source=source, file=self._label, lines=self._lines)

    # ---------------------------------------------------------------- content

    def _content(
        self, element: ET._Element, path: tuple[str, ...]
    ) -> tuple[dict[str, SourceAttribute], dict[str, SourceChild], list[Constraint]]:
        attributes: dict[str, SourceAttribute] = {}
        children: dict[str, SourceChild] = {}
        require: list[Constraint] = []
        field_attributes: list[ET._Element] = []
        for child in element:
            if not isinstance(child.tag, str):
                continue
            tag = _local(child)
            if tag in ("doc", "symbols", "enumeration", "dimensions"):
                continue
            if tag == "attribute":
                if child.get("valueFrom") is not None:
                    self._report.info(
                        "T16",
                        "attribute with valueFrom is the profile's class attribute",
                        self._label,
                        child.sourceline,
                    )
                    continue
                key, member = self._attribute(child, path)
                if key in attributes:
                    self._error(
                        "duplicate-id", f"attribute {key!r} declared twice", child
                    )
                attributes[key] = member
            elif tag in _NODE_OF_ELEMENT:
                key, member = self._child(child, tag, path)
                self._add_child(children, key, member, child)
            elif tag == "choice":
                require.extend(self._choice(child, children, path))
            elif tag == "fieldAttributes":
                field_attributes.extend(
                    c
                    for c in child
                    if isinstance(c.tag, str) and _local(c) == "attribute"
                )
            elif tag == "reused_concepts":
                self._report.info(
                    "T14",
                    "reused_concepts is documentation only",
                    self._label,
                    child.sourceline,
                )
            else:
                self._warn(
                    "unhandled-element", f"element <{tag}> is not translated", child
                )
        if path:
            self._check_free_names(element, attributes, children)
        for attribute_element in field_attributes:  # T15
            for key, member in children.items():
                if member.node != "dataset":
                    continue
                attr_key, attr = self._attribute(attribute_element, (*path, key))
                if attr_key not in member.attributes:
                    attr.via = sort_rows({*(attr.via or []), "T15"})
                    member.attributes[attr_key] = attr
        return attributes, children, require

    def _check_free_names(
        self,
        element: ET._Element,
        attributes: dict[str, SourceAttribute],
        children: dict[str, SourceChild],
    ) -> None:
        """Several ``any`` members of one kind (and class) compete for every name."""
        groups: dict[tuple[str, str | None], list[str]] = {}
        # in NXdata, DATA and AXISNAME are roles (T13), also where a group refines it
        roles = element.get("type") == "NXdata" or element.get("name") == "NXdata"
        for key, member in children.items():
            if isinstance(member.name, AnyName) and not (
                roles and member.node == "dataset"
            ):
                groups.setdefault((member.node, member.class_), []).append(key)
        any_attributes = [
            k for k, a in attributes.items() if isinstance(a.name, AnyName)
        ]
        if len(any_attributes) > 1:
            groups[("attribute", None)] = any_attributes
        for (node, _), keys in sorted(groups.items(), key=lambda item: str(item[0])):
            if len(keys) > 1:
                self._warn(
                    "several-any",
                    f"{node} members {', '.join(keys)} all accept any name",
                    element,
                )

    def _add_child(
        self,
        children: dict[str, SourceChild],
        key: str,
        member: SourceChild,
        element: ET._Element,
    ) -> None:
        if key in children:
            if children[key].node == member.node:
                self._error(
                    "duplicate-id",
                    f"{member.node} {key!r} declared twice in the same group",
                    element,
                )
                return
            member.id = key
            key = f"{key}[{member.node}]"
        children[key] = member

    def _naming(self, element: ET._Element, tag: str) -> tuple[str, Name, list[str]]:
        """The id and the name matcher of a member (T2, T3, T3b)."""
        name = element.get("name")
        name_type = element.get("nameType")
        via: list[str] = []
        if tag == "group" and name is None:
            nx_class = element.get("type") or ""
            via.append("T2")
            if name_type not in (None, "any"):
                self._warn(
                    "nameType-without-name",
                    f"nameType={name_type!r} on a group without name",
                    element,
                )
            return t2_id(nx_class), AnyName(any=True), via
        if name is None:
            self._error("missing-name", f"<{tag}> without name", element)
            return "UNNAMED", AnyName(any=True), via
        self._check_name(name, element)
        effective = name_type or self._facts.default(tag, "nameType") or "specified"
        if effective == "any":
            via.append("T3")
            return name, AnyName(any=True), via
        if effective == "partial":
            via.append("T3")
            template = template_of(name)
            if template == name:
                self._warn(
                    "partial-without-placeholder",
                    f"nameType=partial but {name!r} has no upper case",
                    element,
                )
                return name, ExactName(exact=name), via
            return name, TemplateName(template=template), via
        if effective != "specified":
            self._error("bad-nameType", f"nameType={effective!r}", element)
        if name_type is None and _UPPER_RUN.search(name):
            via.append("T3b")
            self._warn(
                "upper-case-exact",
                f"{name!r} has upper case but no nameType: exact name (T3b)",
                element,
            )
        return name, ExactName(exact=name), via

    def _occurs(
        self, element: ET._Element, node: str
    ) -> tuple[Occurs | None, bool | None, list[str]]:
        """Minimum and maximum occurrence (T4, T5, T6, T7)."""
        via: list[str] = []
        min_value: int | None = None
        recommended: bool | None = None
        written_min = element.get("minOccurs")
        optional = self._bool(element, "optional")
        is_recommended = self._bool(element, "recommended")
        if written_min is not None:
            if written_min.isdigit():
                min_value = int(written_min)
            else:
                self._error("bad-minOccurs", f"minOccurs={written_min!r}", element)
            if optional is not None and (optional != (min_value == 0)):
                self._warn(
                    "conflicting-occurrence",
                    f"minOccurs={written_min} and optional={element.get('optional')}",
                    element,
                )
        elif optional is not None:
            min_value = 0 if optional else 1
        elif is_recommended:
            min_value = 0
        if is_recommended:
            if min_value == 0:
                recommended = True
            else:
                self._warn(
                    "conflicting-occurrence",
                    "recommended on a required member",
                    element,
                )
        if min_value is None:
            via.append("T5" if self._application else "T4")
        else:
            via.append("T6")
        max_value: int | str | None = None
        written_max = element.get("maxOccurs")
        if node in ("group", "dataset"):
            if written_max is None:
                via.append("T7")
            elif written_max == "unbounded":
                max_value = "unbounded"
            elif written_max.isdigit():
                max_value = int(written_max)
            else:
                self._error("bad-maxOccurs", f"maxOccurs={written_max!r}", element)
        if (
            isinstance(max_value, int)
            and min_value is not None
            and max_value < min_value
        ):
            self._warn(
                "max-below-min", f"maxOccurs={max_value} < min {min_value}", element
            )
        occurs = None
        if min_value is not None or max_value is not None:
            occurs = Occurs(min=min_value, max=max_value)
        return occurs, recommended, via

    def _type(self, element: ET._Element) -> tuple[str | None, list[str]]:
        written = element.get("type")
        if written is None:
            return None, ["T0"]
        if written not in self._facts.types:
            self._error(
                "unknown-type", f"type {written!r} is not a NeXus type", element
            )
        return written, []

    def _units(self, element: ET._Element):
        units = element.get("units")
        if units is None:
            return None
        if units in self._facts.units:
            return UnitsCategory(category=units)
        if units.startswith("NX_"):
            self._error(
                "unknown-units-category",
                f"units category {units!r} does not exist",
                element,
            )
            return UnitsCategory(category=units)
        self._warn(
            "units-not-category",
            f"units={units!r} is not a category: fixed units",
            element,
        )
        return UnitsFixed(fixed=units)

    def _enumeration(self, element: ET._Element) -> Enumeration | None:
        """Item values as written; they are typed after resolution (§5.2.7)."""
        for child in element:
            if not isinstance(child.tag, str) or _local(child) != "enumeration":
                continue
            values = []
            for item in child:
                if not isinstance(item.tag, str) or _local(item) != "item":
                    continue
                text = item.get("value")
                if text is None:
                    continue
                if "*" in text:
                    self._warn(
                        "enum-wildcard",
                        f"item {text!r} kept as a literal value (#1234)",
                        item,
                    )
                values.append(
                    EnumValue(
                        value=text,
                        doc=_doc_text(item),
                        deprecated=item.get("deprecated"),
                    )
                )
            is_open = self._bool(child, "open")
            if is_open is None:
                is_open = (self._facts.default("enumeration", "open") or "false") in (
                    "true",
                    "1",
                )
            return Enumeration(values=values, open=is_open)
        return None

    def _dimension_value(self, text: str | None, element: ET._Element, via: list[str]):
        if text is None:
            return None
        text = text.strip()
        if _INTEGER.fullmatch(text):
            return int(text)
        if _IDENTIFIER.fullmatch(text):
            return text
        if _EXPRESSION.fullmatch(text):
            via.append("T9b")
            return DimExpr(expr=expression_of(text))
        self._warn(
            "bad-dimension",
            f"dimension {text!r} is no integer, symbol or expression",
            element,
        )
        return None

    def _shape(self, element: ET._Element) -> tuple[Shape | None, list[str]]:
        for child in element:
            if not isinstance(child.tag, str) or _local(child) != "dimensions":
                continue
            via = ["T9"]
            rank_text = child.get("rank")
            rank: int | str | None = None
            if rank_text is not None:
                rank_text = rank_text.strip()
                if _INTEGER.fullmatch(rank_text):
                    rank = int(rank_text)
                elif _IDENTIFIER.fullmatch(rank_text):
                    rank = rank_text
                    via.append("T9d")
                elif _EXPRESSION.fullmatch(rank_text):
                    rank = DimExpr(expr=expression_of(rank_text))
                    via += ["T9b", "T9d"]
                else:
                    self._warn("bad-rank", f"rank {rank_text!r} dropped", child)
            dims: dict[int, object] = {}
            for dim in child:
                if not isinstance(dim.tag, str) or _local(dim) != "dim":
                    continue
                index_text = dim.get("index", "")
                if not index_text.strip().isdigit() or int(index_text) < 1:
                    self._warn("bad-dim-index", f"dim index {index_text!r}", dim)
                    continue
                index = int(index_text)
                if any(dim.get(a) is not None for a in ("ref", "refindex", "incr")):
                    self._warn(
                        "deprecated-dim-ref",
                        "dim/@ref is deprecated; dimension left open",
                        dim,
                    )
                value = self._dimension_value(dim.get("value"), dim, via)
                if self._bool(dim, "required") is False:
                    via.append("T9c")
                    value = OptionalDim(optional=True, value=value)
                if index in dims:
                    self._warn("duplicate-dim-index", f"dim index {index} twice", dim)
                dims[index] = value
            length = max(dims) if dims else 0
            if isinstance(rank, int):
                if length > rank:
                    self._warn(
                        "rank-mismatch", f"rank {rank} but dim index {length}", child
                    )
                length = max(length, rank)
            dim_list = [dims.get(i) for i in range(1, length + 1)] if length else None
            if dim_list is not None and isinstance(rank, int) and rank == len(dim_list):
                rank = None
            if dim_list is None and rank is None:
                return Shape(), via
            return Shape(rank=rank, dims=dim_list), sort_rows(via)
        return None, []

    # ----------------------------------------------------------------- members

    def _attribute(
        self, element: ET._Element, path: tuple[str, ...]
    ) -> tuple[str, SourceAttribute]:
        self._check_attributes(element, "attribute")
        key, name, via = self._naming(element, "attribute")
        occurs, recommended, occurs_via = self._occurs(element, "attribute")
        type_name, type_via = self._type(element)
        shape, shape_via = self._shape(element)
        self._lines[(*path, "@" + key)] = element.sourceline
        all_via = sort_rows({"T1", *via, *occurs_via, *type_via, *shape_via})
        show = [element.get("reused_from")] if element.get("reused_from") else None
        return key, SourceAttribute(
            name=None if isinstance(name, ExactName) and name.exact == key else name,
            occurs=occurs,
            recommended=recommended,
            type=type_name,
            shape=shape,
            enum=self._enumeration(element),
            deprecated=element.get("deprecated"),
            doc=_doc_text(element),
            show=show,
            via=all_via,
            provisional=provisional_for(all_via) or None,
        )

    def _child(
        self, element: ET._Element, tag: str, path: tuple[str, ...]
    ) -> tuple[str, SourceChild]:
        self._check_attributes(element, tag)
        node = _NODE_OF_ELEMENT[tag]
        key, name, via = self._naming(element, tag)
        member_path = (*path, key)
        self._lines[member_path] = element.sourceline
        occurs, recommended, occurs_via = self._occurs(element, node)
        via = ["T1", *via, *occurs_via]
        data: dict = {
            "node": node,
            "name": None if isinstance(name, ExactName) and name.exact == key else name,
            "occurs": occurs,
            "recommended": recommended,
            "deprecated": element.get("deprecated"),
            "doc": _doc_text(element),
        }
        if element.get("reused_from"):
            data["show"] = [element.get("reused_from")]
            via.append("T14")
        if node == "group":
            nx_class = element.get("type")
            if (
                nx_class
                and self._class_re is not None
                and not self._class_re.fullmatch(nx_class)
            ):
                self._error("invalid-class-name", f"type {nx_class!r}", element)
            data["class_"] = nx_class
            attributes, children, require = self._content(element, member_path)
            data.update(attributes=attributes, children=children, require=require)
        elif node == "dataset":
            type_name, type_via = self._type(element)
            shape, shape_via = self._shape(element)
            via += type_via + shape_via
            attributes, _, _ = self._content(element, member_path)
            self._legacy_attributes(element, attributes, member_path)
            data.update(
                type=type_name,
                shape=shape,
                units=self._units(element),
                enum=self._enumeration(element),
                attributes=attributes,
            )
        else:
            target = element.get("target") or ""
            if self._target_re is not None and not self._target_re.fullmatch(target):
                self._warn(
                    "bad-target",
                    f"target {target!r} does not match the target grammar",
                    element,
                )
            data["target"] = target_to_ids(target, absolute=not self._application)
            via.append("T10")
        all_via = sort_rows(via)
        data["via"] = all_via
        data["provisional"] = provisional_for(all_via) or None
        return key, SourceChild(**data)

    def _legacy_attributes(
        self,
        element: ET._Element,
        attributes: dict[str, SourceAttribute],
        path: tuple[str, ...],
    ) -> None:
        """Field attributes such as ``signal="1"`` (T19)."""
        types = self._facts.attribute_types.get("field", {})
        for legacy in _LEGACY_FIELD_ATTRIBUTES:
            value = element.get(legacy)
            if value is None:
                continue
            if legacy in attributes:
                self._warn(
                    "legacy-attribute",
                    f"{legacy}={value!r} and an attribute {legacy!r}",
                    element,
                )
                continue
            type_name = types.get(legacy)
            type_name = type_name if type_name in self._facts.types else None
            parts = value.split()
            # T19: a value with spaces is a list value
            enum = Enumeration(
                values=[EnumValue(value=parts if len(parts) > 1 else value)]
            )
            attributes[legacy] = SourceAttribute(
                occurs=Occurs(min=0), type=type_name, enum=enum, via=["T19"]
            )
            self._lines[(*path, "@" + legacy)] = element.sourceline

    def _choice(
        self,
        element: ET._Element,
        children: dict[str, SourceChild],
        path: tuple[str, ...],
    ) -> list[Constraint]:
        """One member per alternative plus a constraint over them (T11)."""
        name = element.get("name") or "choice"
        ids = []
        for group in element:
            if not isinstance(group.tag, str) or _local(group) != "group":
                continue
            nx_class = group.get("type") or ""
            key = f"{name}_{t2_id(nx_class)}"
            _, member = self._child(group, "group", path)
            member.name = ExactName(exact=name)
            member.occurs = Occurs(min=0, max=1)
            member.via = sort_rows({*(member.via or []), "T11"})
            self._lines[(*path, key)] = group.sourceline
            self._add_child(children, key, member, group)
            ids.append(key)
        if self._application:
            return [ExactlyOneOf(exactly_one_of=ids)]
        return [AtMostOneOf(at_most_one_of=ids)]

    # ---------------------------------------------------------- class-specific

    def _class_specific(self, source: SourceClass) -> None:
        """T13: prose about NXdata and NXobject turned into declarations."""
        if source.class_ == "NXdata":
            for key, role in (("DATA", "@signal"), ("AXISNAME", "@axes")):
                member = source.children.get(key)
                if member is not None and member.node == "dataset":
                    member.name = RefName(ref=role)
                    member.via = sort_rows({*(member.via or []), "T13"})
            auxiliary = source.attributes.get("auxiliary_signals")
            if auxiliary is not None:
                auxiliary.names_child = "dataset"
                auxiliary.via = sort_rows({*(auxiliary.via or []), "T13"})
        if source.class_ == OBJECT_CLASS:
            default = source.attributes.get("default")
            if default is not None:
                default.names_child = "group"
                default.via = sort_rows({*(default.via or []), "T13"})
