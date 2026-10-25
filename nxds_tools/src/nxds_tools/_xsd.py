"""Facts read from ``nxdl.xsd`` (and the ``nxdlTypes.xsd`` it includes)."""

import re
import textwrap
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import lxml.etree as ET
import xmlschema
from xmlschema.validators.simple_types import XsdAtomicBuiltin
from xmlschema.validators.simple_types import XsdList
from xmlschema.validators.simple_types import XsdUnion

from ._units import UnitsError
from ._units import dimensions
from ._units import empty_categories
from .model import NameGrammar
from .model import TypeDef
from .model import UnitsCategoryDef

_XS = "{http://www.w3.org/2001/XMLSchema}"


@dataclass
class XsdFacts:
    """What the NXDL grammar states: attribute defaults, types, units, names."""

    #: element → attribute → XSD default (``None`` when there is none)
    attributes: dict[str, dict[str, str | None]] = field(default_factory=dict)
    #: element → attribute → name of its XSD type
    attribute_types: dict[str, dict[str, str | None]] = field(default_factory=dict)
    #: element → names of the child elements it may contain
    children: dict[str, set[str]] = field(default_factory=dict)
    types: dict[str, TypeDef] = field(default_factory=dict)
    units: dict[str, UnitsCategoryDef] = field(default_factory=dict)
    names: NameGrammar | None = None
    #: the characters a template placeholder stands for (Q3; copied to the profile)
    placeholder_characters: str = "[^/]"

    def default(self, element: str, attribute: str) -> str | None:
        return self.attributes.get(element, {}).get(attribute)

    def is_narrower(self, narrow: str, wide: str) -> bool:
        """Whether every value of type ``narrow`` is a value of type ``wide``."""
        return is_narrower(self.types, narrow, wide)


def is_narrower(types: dict[str, TypeDef], narrow: str, wide: str) -> bool:
    """Whether ``narrow`` equals ``wide``, is a member of it or derives from it."""
    if narrow == wide:
        return True
    wide_def = types.get(wide)
    if wide_def is not None and wide_def.variety == "union":
        if any(is_narrower(types, narrow, member) for member in wide_def.members):
            return True
    narrow_def = types.get(narrow)
    if narrow_def is None:
        return False
    if narrow_def.base in types:
        return is_narrower(types, narrow_def.base, wide)
    if wide_def is not None and wide_def.variety == "atomic" and wide_def.builtins:
        return wide_def.builtins[0] in narrow_def.builtins
    return False


def load_facts(definitions: Path) -> XsdFacts:
    """Read the grammar of the definitions directory being compiled."""
    schema = xmlschema.XMLSchema(str(definitions / "nxdl.xsd"), validation="skip")
    facts = XsdFacts()
    root_name = next(iter(schema.elements))
    _walk_element(schema.elements[root_name], facts, set())
    facts.types = _types(schema)
    facts.units = _units(schema)
    facts.names, facts.placeholder_characters = _names(schema)
    return facts


def _walk_element(element, facts: XsdFacts, seen: set) -> None:
    name = element.local_name
    xsd_type = element.type
    key = (name, xsd_type.name)
    if key in seen:
        return
    seen.add(key)
    attrs = facts.attributes.setdefault(name, {})
    attr_types = facts.attribute_types.setdefault(name, {})
    for attr_name, attr in getattr(xsd_type, "attributes", {}).items():
        if attr_name is not None:
            attrs.setdefault(attr_name, attr.default)
            attr_types.setdefault(attr_name, attr.type.local_name)
    children = facts.children.setdefault(name, set())
    if xsd_type.has_complex_content() or xsd_type.mixed:
        for child in xsd_type.content.iter_elements():
            if getattr(child, "local_name", None):
                children.add(child.local_name)
                _walk_element(child, facts, seen)


def _doc(xsd_type) -> str | None:
    texts = []
    for annotation in xsd_type.annotations:
        for doc in annotation.documentation:
            text = doc.text or ""
            texts.append(textwrap.dedent(text.strip("\n")).strip())
    text = "\n\n".join(t for t in texts if t)
    return text or None


def _union_member_names(xsd_type) -> list[str]:
    return [m.local_name for m in xsd_type.member_types if m.local_name]


def _types(schema) -> dict[str, TypeDef]:
    """The type lattice reachable from the type of ``field/@type``."""
    root = schema.types.get("primitiveType")
    types: dict[str, TypeDef] = {}
    if root is None:
        return types
    pending = _union_member_names(root)
    while pending:
        name = pending.pop()
        if name in types or name not in schema.types:
            continue
        xsd_type = schema.types[name]
        if isinstance(xsd_type, XsdUnion):
            members = _union_member_names(xsd_type)
            types[name] = TypeDef(variety="union", members=members, doc=_doc(xsd_type))
            pending.extend(members)
            continue
        base = xsd_type.base_type
        list_base = base
        while list_base is not None and not isinstance(list_base, XsdList):
            list_base = list_base.base_type
        if list_base is not None:
            length = None
            facet = xsd_type.facets.get(f"{_XS}length")
            if facet is not None:
                length = int(facet.value)
            item = list_base.item_type
            types[name] = TypeDef(
                variety="list",
                base=item.prefixed_name if item is not None else None,
                length=length,
                doc=_doc(xsd_type),
            )
            continue
        if (
            base is not None
            and base.local_name in schema.types
            and not isinstance(base, XsdAtomicBuiltin)
        ):
            base_name = base.local_name
            pending.append(base_name)
        else:
            base_name = base.prefixed_name if base is not None else None
        min_value = getattr(xsd_type, "min_value", None)
        builtins = []
        ancestor = base
        while ancestor is not None:
            if isinstance(ancestor, XsdAtomicBuiltin):
                builtins.append(ancestor.prefixed_name)
            ancestor = ancestor.base_type
        types[name] = TypeDef(
            variety="atomic",
            base=base_name,
            builtins=builtins,
            min_value=float(min_value) if min_value is not None else None,
            doc=_doc(xsd_type),
        )
    return dict(sorted(types.items()))


def _examples(xsd_type) -> list[str]:
    examples = []
    for annotation in xsd_type.annotations:
        for container in (*annotation.appinfo, *annotation.documentation):
            for child in container:
                if not isinstance(child.tag, str):
                    continue
                if ET.QName(child.tag).localname in ("example", "element"):
                    text = (child.text or "").strip()
                    examples.append("" if text in ('""', "''") else text)
    return examples


def _units(schema) -> dict[str, UnitsCategoryDef]:
    """Units categories: the NeXus members of the type of ``field/@units``."""
    if "anyUnitsAttr" not in schema.types:
        return {}
    root = schema.types["anyUnitsAttr"]
    result: dict[str, UnitsCategoryDef] = {}
    names = [n for n in _union_member_names(root) if n in schema.types]
    for name in names:
        xsd_type = schema.types[name]
        members = (
            _union_member_names(xsd_type) if isinstance(xsd_type, XsdUnion) else []
        )
        result[name] = UnitsCategoryDef(
            members=members, examples=_examples(xsd_type), doc=_doc(xsd_type)
        )
    empty = set(empty_categories())
    for name, category in result.items():
        category.dimensions = _category_dimensions(name, result, set())
        category.empty = name in empty
    return dict(sorted(result.items()))


def _category_dimensions(
    name: str, categories: dict[str, UnitsCategoryDef], seen: set[str]
) -> list[dict[str, int]] | None:
    """Distinct dimensions of the example units of a category and its members."""
    if name in seen or name not in categories:
        return None
    seen.add(name)
    category = categories[name]
    found: list[dict[str, int]] = []
    for example in category.examples:
        try:
            dims = dimensions(example)
        except UnitsError:
            continue
        if dims not in found:
            found.append(dims)
    for member in category.members:
        for dims in _category_dimensions(member, categories, seen) or []:
            if dims not in found:
                found.append(dims)
    return found or None


def _first_pattern(xsd_type) -> str | None:
    while xsd_type is not None:
        patterns = getattr(xsd_type, "patterns", None)
        if patterns is not None and patterns.regexps:
            return patterns.regexps[0]
        xsd_type = xsd_type.base_type
    return None


def _names(schema) -> tuple[NameGrammar, str]:
    item = schema.types["validItemName"]
    item_pattern = _first_pattern(item) or ".+"
    max_length = item.max_length
    nx_class = schema.types["validNXClassName"]
    class_pattern = _first_pattern(nx_class) or ".+"
    target = schema.types.get("validTargetName")
    # the placeholder characters are the widest character class of the name grammar
    classes = re.findall(r"\[[^\]]+\]", item_pattern)
    placeholder = max(classes, key=len) if classes else "[^/]"
    grammar = NameGrammar(
        item_pattern=item_pattern,
        item_max_length=max_length,
        class_pattern=class_pattern,
        target_pattern=_first_pattern(target) if target is not None else None,
    )
    return grammar, placeholder
