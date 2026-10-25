"""Pydantic models of NXDS: the source form, the resolved form and the bundle."""

import inspect
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import AfterValidator
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

NXDS_VERSION = "0.1"

Unbounded = Literal["unbounded"]
NodeKind = Literal["group", "dataset", "link"]
Policy = Literal["report", "ignore", "error"]
Category = Literal["base", "application"]
Status = Literal["base", "application", "contributed", "dormant", "local"]
#: what each status means (documentation only; it never changes a check)
STATUSES: dict[str, str] = {
    "base": "in base_classes/",
    "application": "in applications/",
    "contributed": "in contributed_definitions/",
    "dormant": "in a dormant or stagnant subdirectory",
    "local": "in a class directory given in addition to the repository; not released",
}
STATUS_DOC = "; ".join(f"{k}: {v}" for k, v in STATUSES.items())


def _clean_doc(text: str) -> str:
    return inspect.cleandoc(text)


#: documentation text, without common indentation or surrounding blank lines
DocText = Annotated[str, AfterValidator(_clean_doc)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ------------------------------------------------------------------ matchers


class ExactName(_Model):
    """The object has exactly this name."""

    exact: str


class TemplateName(_Model):
    """Each ``{PLACEHOLDER}`` stands for one or more name characters."""

    template: str


class AnyName(_Model):
    """Any valid name."""

    any: Literal[True]


class RefName(_Model):
    """A role: the child named by an attribute of the parent (``@signal``)."""

    ref: str


Name = ExactName | TemplateName | AnyName | RefName


def name_kind(name: Name) -> str:
    """``exact``, ``template``, ``any`` or ``ref``."""
    if isinstance(name, ExactName):
        return "exact"
    if isinstance(name, TemplateName):
        return "template"
    if isinstance(name, AnyName):
        return "any"
    return "ref"


# ---------------------------------------------------------- value constraints


class Occurs(_Model):
    """Occurrence; in the source form either bound may be omitted."""

    min: int | None = Field(default=None, ge=0)
    max: int | Unbounded | None = None


class ResolvedOccurs(_Model):
    """Occurrence with both bounds explicit."""

    min: int = Field(ge=0)
    max: int | Unbounded


Scalar = str | int | float | bool


class EnumValue(_Model):
    """One allowed value: a scalar applies to each element of an array, a list
    to the whole array (§4.5)."""

    value: Scalar | list[Scalar]
    doc: DocText | None = None
    deprecated: str | None = None


class Enumeration(_Model):
    """Allowed values; an open enumeration only advises."""

    values: list[EnumValue]
    open: bool = False

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, list):
            data = {"values": data, "open": False}
        if isinstance(data, dict) and isinstance(data.get("values"), list):
            values = [
                v if isinstance(v, (dict, EnumValue)) else {"value": v}
                for v in data["values"]
            ]
            return {**data, "values": values}
        return data


class DimExpr(_Model):
    """A dimension given as an expression of symbols and integers with ``+``, ``-``
    and ``*`` (``tof+1``, ``2*n``)."""

    expr: str


class OptionalDim(_Model):
    """A dimension that may be absent (NXDL ``dim/@required="false"``)."""

    optional: Literal[True]
    value: int | str | DimExpr | None = None


Dim = int | str | DimExpr | OptionalDim | None


class Shape(_Model):
    """Rank and dimensions; ``binding: false`` shapes are documentation only."""

    rank: int | str | DimExpr | None = None
    dims: list[Dim] | None = None
    binding: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"dims": data}
        return data


class ResolvedShape(Shape):
    """A shape of the resolved form: ``symbols`` names the class declaring each symbol."""

    symbols: dict[str, str] = {}


class UnitsCategory(_Model):
    """Units of a category (``NX_ENERGY``)."""

    category: str


class UnitsFixed(_Model):
    """Exactly these units."""

    fixed: str


Units = UnitsCategory | UnitsFixed


class RankOf(_Model):
    """As many entries as the member has dimensions."""

    rank_of: str


Length = int | str | RankOf


class AtLeastOneOf(_Model):
    at_least_one_of: list[str]


class ExactlyOneOf(_Model):
    exactly_one_of: list[str]


class AtMostOneOf(_Model):
    at_most_one_of: list[str]


class AllOrNone(_Model):
    all_or_none: list[str]


Constraint = AtLeastOneOf | ExactlyOneOf | AtMostOneOf | AllOrNone


def constraint_kind(constraint: Constraint) -> tuple[str, list[str]]:
    """The kind of a constraint and the member ids it is over."""
    ((kind, members),) = constraint.model_dump().items()
    return kind, members


def _require_list(data: Any) -> Any:
    if isinstance(data, dict):
        return [{key: value} for key, value in data.items()]
    return data


class UndeclaredPerKind(_Model):
    """Policy for undeclared objects, per node kind."""

    group: Policy = "report"
    dataset: Policy = "report"
    attribute: Policy = "report"


Undeclared = Policy | UndeclaredPerKind


# --------------------------------------------------------------- source form


class _SourceMember(_Model):
    name: Name | None = None
    occurs: Occurs | None = None
    recommended: bool | None = None
    type: str | None = None
    shape: Shape | None = None
    units: Units | None = None
    enum: Enumeration | None = None
    length: Length | None = None
    rank: int | str | None = None
    names_child: Literal["group", "dataset"] | None = None
    refines: str | None = None
    deprecated: str | None = None
    doc: DocText | None = None
    show: list[str] | None = None
    via: list[str] | None = None
    provisional: list[str] | None = None


class SourceAttribute(_SourceMember):
    """An attribute member as written by an author."""


class SourceChild(_SourceMember):
    """A child member (group, dataset or link) as written by an author."""

    #: the id, when it differs from the key (a dataset and a group sharing an id)
    id: str | None = None
    node: NodeKind
    class_: str | None = Field(default=None, alias="class")
    attributes: dict[str, SourceAttribute] = {}
    children: dict[str, "SourceChild"] = {}
    require: list[Constraint] = []
    undeclared: Undeclared | None = None
    target: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _require_shorthand(cls, data: Any) -> Any:
        if isinstance(data, dict) and "require" in data:
            return {**data, "require": _require_list(data["require"])}
        return data


class Defaults(_Model):
    """Defaults for the members written in one class file."""

    min: int = Field(ge=0)
    binding: bool
    type: str | None = None


class Symbol(_Model):
    """A named dimension length."""

    doc: DocText | None = None


class SourceClass(_Model):
    """An NXDS class as written by an author (or translated from NXDL)."""

    nxds: str = NXDS_VERSION
    class_: str = Field(alias="class")
    category: Category
    extends: str | None = None
    describes: str | None = None
    deprecated: str | None = None
    doc: DocText | None = None
    defaults: Defaults
    symbols: dict[str, Symbol] = {}
    attributes: dict[str, SourceAttribute] = {}
    children: dict[str, SourceChild] = {}
    require: list[Constraint] = []
    undeclared: Undeclared | None = None
    via: list[str] | None = None
    provisional: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _require_shorthand(cls, data: Any) -> Any:
        if isinstance(data, dict) and "require" in data:
            return {**data, "require": _require_list(data["require"])}
        return data


# ------------------------------------------------------------- resolved form


class MemberRef(_Model):
    """A member identical to one listed in full elsewhere: ``NXobject/DATA``.

    ``<scope>/<label path>`` for a child (with ``node``) or ``<scope>@<label>``
    for an attribute, where the scope is the longest prefix that is a class
    name or a specialisation id (§6.3). The member it names is listed in full
    there, so a reader follows at most one reference.
    """

    ref: str
    node: NodeKind | None = None


class _ResolvedMember(_Model):
    id: str
    name: Name
    occurs: ResolvedOccurs
    recommended: bool = False
    type: str | None = None
    shape: ResolvedShape | None = None
    units: Units | None = None
    enum: Enumeration | None = None
    length: Length | None = None
    rank: int | str | None = None
    names_child: Literal["group", "dataset"] | None = None
    deprecated: str | None = None
    #: keys of the documentation texts of this member, most derived last
    docs: list[str] = []
    show: list[str] | None = None
    declared_by: str
    refined_by: list[str] = []
    refines: str | None = None
    provisional: list[str] = []
    via: list[str] = []


class ResolvedAttribute(_ResolvedMember):
    """An attribute member with everything explicit."""


class ResolvedChild(_ResolvedMember):
    """A child member with everything explicit."""

    node: NodeKind
    class_: str | None = Field(default=None, alias="class")
    specialisation: str | None = None
    attributes: list[ResolvedAttribute] = []
    target: str | None = None


class _ResolvedGroup(_Model):
    class_: str = Field(alias="class")
    symbols: list[str] = []
    attributes: list[ResolvedAttribute | MemberRef] = []
    children: list[ResolvedChild | MemberRef] = []
    require: list[Constraint] = []
    undeclared: UndeclaredPerKind = UndeclaredPerKind()


class ResolvedClass(_ResolvedGroup):
    """A class with all inherited members merged in."""

    category: Category
    status: Status = Field(description=STATUS_DOC)
    extends: str | None = None
    describes: str | None = None
    deprecated: str | None = None
    lossy: list[str] = []
    source: str
    provisional: list[str] = []
    via: list[str] = []


class Specialisation(_ResolvedGroup):
    """A group as a class refines it, e.g. ``NXdemo/ENTRY/DATA``."""

    id: str
    declared_by: str


class ResolvedDocument(_Model):
    """The resolved form of one class and its specialisations (one file)."""

    nxds: str = NXDS_VERSION
    #: language features outside the core that this file uses
    requires: list[str] = []
    definition: ResolvedClass
    specialisations: dict[str, Specialisation] = {}


# -------------------------------------------------------------------- bundle


class TypeDef(_Model):
    """A NeXus data type, as declared in nxdlTypes.xsd."""

    variety: Literal["atomic", "list", "union"]
    base: str | None = None
    builtins: list[str] = []
    members: list[str] = []
    length: int | None = None
    min_value: float | None = None
    doc: DocText | None = None


class UnitsCategoryDef(_Model):
    """A units category with its example units and dimensions."""

    members: list[str] = []
    examples: list[str] = []
    dimensions: list[dict[str, int]] | None = None
    #: an empty unit string is accepted (§14)
    empty: bool = False
    doc: DocText | None = None


class NameGrammar(_Model):
    """Name constraints from nxdl.xsd."""

    item_pattern: str
    item_max_length: int | None
    class_pattern: str
    target_pattern: str | None = None


class StorageProfile(_Model):
    """How the abstract tree is stored in a format (HDF5)."""

    name: str
    class_attribute: str
    units_attribute: str
    root_class: str
    entry_points: list[str]
    dispatch_dataset: str
    release_attribute: str
    link_target_attribute: str
    #: characters a template placeholder stands for (a regular expression class)
    placeholder_characters: str
    #: the attribute and value marking an entry whose scan was stopped (Q10)
    stopped_attribute: str
    stopped_value: str
    links: dict[str, str]
    #: storage types accepted per data type, every type of the index listed
    storage: dict[str, list[str]]


Severity = Literal["E", "W", "I"]


PartialRule = Literal["kept", "always", "growing", "missing", "dangling", "absent"]


class Code(_Model):
    """A finding code: severity and its exceptions, path rule, partial-mode rule."""

    severity: Severity
    #: condition → the severity used instead when it holds
    exceptions: dict[str, Severity] = {}
    #: where the finding is reported
    path: str
    #: when partial mode reports it as INCOMPLETE: never (``kept``), ``always``,
    #: or only under the named condition (a dataset involved can still ``grow``,
    #: it fails because objects are ``missing``, the link is ``dangling``, the
    #: object is ``absent``)
    partial: PartialRule
    tier: str | None = None
    doc: str


class UnitSymbols(_Model):
    """Unit symbols and their dimensions (powers of base dimensions)."""

    prefixes: dict[str, int]
    #: symbols that take an SI prefix
    prefixed: dict[str, dict[str, int]]
    #: symbols without prefix
    plain: dict[str, dict[str, int]]


class ClassEntry(_Model):
    """What the index says about a class, so a reader loads it only when needed."""

    category: Category
    status: Status = Field(description=STATUS_DOC)
    extends: str | None = None
    describes: str | None = None
    specialisations: int = 0


class Index(_Model):
    """Everything of a bundle except the classes: vocabularies, profiles, codes, class list."""

    nxds: str = NXDS_VERSION
    release: str
    revision: int = 1
    #: language features outside the core used by any class of the bundle
    features: list[str] = []
    decisions: dict[str, str] = {}
    statuses: dict[str, str] = {}
    types: dict[str, TypeDef] = {}
    units: dict[str, UnitsCategoryDef] = {}
    names: NameGrammar
    unit_symbols: UnitSymbols
    profiles: dict[str, StorageProfile] = {}
    codes: dict[str, Code] = {}
    classes: dict[str, ClassEntry] = {}


class Bundle(Index):
    """The resolved NXDS of one release: the index and every resolved document."""

    documents: dict[str, ResolvedDocument] = {}


class CatalogueEntry(_Model):
    """One published bundle of a release."""

    release: str
    revision: int = Field(ge=1)
    status: Literal["current", "superseded", "withdrawn"]
    #: the bundle file or directory, relative to the catalogue
    path: str


class Catalogue(_Model):
    """``nxds-index.json``: every published bundle (§12.3)."""

    nxds: str = NXDS_VERSION
    bundles: list[CatalogueEntry]


class Finding(_Model):
    """One finding of a validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Severity
    path: str
    member: str | None
    bundle: str
    message: str | None = None
    expected: str | None = None
    actual: str | None = None


class DocsDocument(_Model):
    """Documentation texts written by one class, by key (``NXentry/title``,
    ``NXentry`` for the class, ``NXentry#nE`` for a symbol, ``…/mode=timer`` for
    an enumeration value)."""

    nxds: str = NXDS_VERSION
    texts: dict[str, str] = {}


SourceChild.model_rebuild()
