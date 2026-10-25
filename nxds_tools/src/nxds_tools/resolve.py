"""Source forms → resolved form per class, and the bundle."""

import re
from dataclasses import dataclass
from dataclasses import replace
from functools import cache
from importlib import resources
from types import SimpleNamespace
from typing import Literal

import yaml

from ._report import Report
from ._units import unit_symbols
from ._xsd import XsdFacts
from .model import STATUSES
from .model import Bundle
from .model import ClassEntry
from .model import Code
from .model import DimExpr
from .model import Enumeration
from .model import ExactName
from .model import Index
from .model import MemberRef
from .model import Name
from .model import OptionalDim
from .model import RefName
from .model import ResolvedAttribute
from .model import ResolvedChild
from .model import ResolvedClass
from .model import ResolvedDocument
from .model import ResolvedOccurs
from .model import ResolvedShape
from .model import Shape
from .model import SourceChild
from .model import Specialisation
from .model import StorageProfile
from .model import TemplateName
from .model import TypeDef
from .model import UndeclaredPerKind
from .model import constraint_kind
from .model import name_kind
from .nxdl import CompiledClass
from .nxdl import t2_id
from .nxdl import typed_enum
from .translation import DECISIONS
from .translation import sort_rows

Origin = Literal["nxdl", "nxds"]
_Member = ResolvedChild | ResolvedAttribute
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
#: the data type of a new member when its file's defaults state none (§3.1)
_DEFAULT_TYPE = "NX_CHAR"
_STEP = re.compile(r"(?P<label>[^\[\]]+)(?:\[(?P<kind>group|dataset|link)\])?")


def label_step(step: str) -> tuple[str, str | None]:
    """``DATA[group]`` → ``("DATA", "group")``; ``energy`` → ``("energy", None)``."""
    match = _STEP.fullmatch(step)
    if match is None:
        return step, None
    return match.group("label"), match.group("kind")


@dataclass
class SourceUnit:
    """One class file: its source form, where it comes from and its status."""

    compiled: CompiledClass
    status: str
    origin: Origin


@dataclass(frozen=True)
class _Context:
    owner: str
    unit: SourceUnit
    spec_prefix: str
    #: symbol → the class declaring it, as seen from the members written here
    symbols: dict[str, str]

    @property
    def nxdl(self) -> bool:
        """Whether the members are translated from NXDL (``via`` is recorded)."""
        return self.unit.origin == "nxdl"


def load_profile(facts: XsdFacts | None = None) -> StorageProfile:
    """The HDF5 storage profile shipped with the tools.

    With ``facts``, the placeholder characters come from the name rules and the
    storage types are listed for every data type (spec §13.1).
    """
    data = dict(_data("hdf5.yaml"))
    data.setdefault(
        "placeholder_characters",
        facts.placeholder_characters if facts is not None else "[^/]",
    )
    if facts is not None:
        data["storage"] = expand_storage(data["storage"], facts.types)
    return StorageProfile.model_validate(data)


def expand_storage(
    storage: dict[str, list[str]], types: dict[str, TypeDef]
) -> dict[str, list[str]]:
    """Storage types of every data type: a union takes those of its members, a
    type with a base and no own entry those of its base (spec §13.1)."""
    result: dict[str, list[str]] = {}

    def of(name: str, seen: frozenset[str]) -> list[str]:
        if name in storage:
            return list(storage[name])
        type_def = types.get(name)
        if type_def is None or name in seen:
            return []
        if type_def.variety == "union":
            found: list[str] = []
            for member in type_def.members:
                found += [s for s in of(member, seen | {name}) if s not in found]
            return found
        if type_def.base in types:
            return of(type_def.base, seen | {name})
        return []

    for name in sorted({*storage, *types}):
        result[name] = of(name, frozenset())
    return result


def load_codes() -> dict[str, Code]:
    """The catalogue of finding codes."""
    return {k: Code.model_validate(v) for k, v in _data("codes.yaml").items()}


@cache
def _data(name: str) -> dict:
    return yaml.safe_load(
        resources.files("nxds_tools").joinpath(f"data/{name}").read_text()
    )


def template_regex(template: str, placeholder: str) -> re.Pattern:
    """The regular expression of a template matcher (placeholders: one or more characters)."""
    parts = re.split(r"(\{[^}]*\})", template)
    pattern = "".join(
        (
            f"{placeholder}+"
            if part.startswith("{") and part.endswith("}")
            else re.escape(part)
        )
        for part in parts
    )
    return re.compile(pattern)


def fixed_characters(template: str) -> int:
    """Number of characters of a template outside its placeholders."""
    return len(re.sub(r"\{[^}]*\}", "", template))


def form_of(node: str) -> str:
    """The form of a node in an identity (§5.1): a link is a dataset form."""
    return "dataset" if node == "link" else node


def node_of(member: _Member) -> str:
    return member.node if isinstance(member, ResolvedChild) else "attribute"


class Resolver:
    """Resolves source forms into resolved classes and specialisations."""

    def __init__(
        self,
        units: dict[str, SourceUnit],
        facts: XsdFacts,
        profile: StorageProfile,
        report: Report,
    ) -> None:
        self._units = units
        self._facts = facts
        self._profile = profile
        self._report = report
        self._classes: dict[str, ResolvedClass | None] = {}
        self._specs: dict[str, Specialisation] = {}
        #: specialisation id → the class or specialisation it was built from
        self._spec_base: dict[str, str] = {}
        #: class → documentation key → text written by that class
        self.docs: dict[str, dict[str, str]] = {}
        self._homes: dict[tuple[str, str, str], str] = {}
        self._in_progress: list[str] = []
        #: (class, label) → the form of a link member it writes (§5.1)
        self._link_forms: dict[tuple[str, str, str], str] = {}
        self._unresolved: set[tuple[str, str, str]] = set()
        #: class → symbol → the class declaring it (own symbols first)
        self._symbols: dict[str, dict[str, str]] = {}
        names = facts.names
        self._placeholder = facts.placeholder_characters
        self._item_re = re.compile(names.item_pattern) if names else re.compile(".+")
        self._templates: dict[str, re.Pattern] = {}

    # ------------------------------------------------------------------ public

    def resolve_all(self) -> dict[str, ResolvedDocument]:
        """Resolve every class; one document per class."""
        for name in sorted(self._units):
            self.resolve(name)
        documents = {}
        for name in sorted(self._units):
            resolved = self._classes.get(name)
            if resolved is None:
                continue
            specs = self.specialisations_of(name)
            documents[name] = ResolvedDocument(
                requires=features_of([resolved, *specs.values()]),
                definition=resolved,
                specialisations=specs,
            )
            self._check_links(name, resolved, specs)
            self._check_require(name, resolved, specs)
        return documents

    def specialisations_of(self, name: str) -> dict[str, Specialisation]:
        """The specialisations a class declares, sorted by id."""
        prefix = name + "/"
        return {k: v for k, v in sorted(self._specs.items()) if k.startswith(prefix)}

    def resolve(self, name: str) -> ResolvedClass | None:
        """The resolved form of one class (memoised)."""
        if name in self._classes:
            return self._classes[name]
        if name not in self._units:
            return None
        if name in self._in_progress:
            return None
        self._in_progress.append(name)
        try:
            result = self._resolve(name)
        finally:
            self._in_progress.pop()
        self._classes[name] = result
        return result

    def is_subclass(self, name: str, parent: str) -> bool:
        """Whether ``name`` is ``parent`` or extends it."""
        seen = set()
        while name and name not in seen:
            if name == parent:
                return True
            seen.add(name)
            unit = self._units.get(name)
            if unit is None:
                return False
            source = unit.compiled.source
            name = source.extends or source.describes
        return False

    # ------------------------------------------------------------------ helpers

    def _location(self, ctx: _Context, path: tuple[str, ...]) -> tuple[str, int | None]:
        lines = ctx.unit.compiled.lines
        while path and path not in lines:
            path = path[:-1]
        return ctx.unit.compiled.file, lines.get(path)

    def _warn(
        self, ctx: _Context, path: tuple[str, ...], code: str, message: str
    ) -> None:
        file, line = self._location(ctx, path)
        self._report.warning(code, message, file, line)

    def _error(
        self, ctx: _Context, path: tuple[str, ...], code: str, message: str
    ) -> None:
        file, line = self._location(ctx, path)
        self._report.error(code, message, file, line)

    def matches(self, name: Name, value: str) -> bool:
        """Whether a name matcher accepts an object name."""
        if isinstance(name, ExactName):
            return name.exact == value
        if isinstance(name, TemplateName):
            regex = self._templates.get(name.template)
            if regex is None:
                regex = template_regex(name.template, self._placeholder)
                self._templates[name.template] = regex
            return regex.fullmatch(value) is not None
        if isinstance(name, RefName):
            return False
        return self._item_re.fullmatch(value) is not None

    def _class_for(self, name: str | None, ctx: _Context, path: tuple[str, ...]):
        if not name:
            return None
        if name not in self._units:
            self._error(ctx, path, "unknown-class", f"class {name!r} does not exist")
            return None
        if name in self._in_progress:
            self._warn(
                ctx,
                path,
                "cyclic-specialisation",
                f"{name} is being resolved; its members are not merged here",
            )
            return None
        return self.resolve(name)

    # ------------------------------------------------------------------- class

    def _resolve(self, name: str) -> ResolvedClass | None:
        unit = self._units[name]
        source = unit.compiled.source
        base_name = source.extends or source.describes
        base = None
        ctx = _Context(owner=name, unit=unit, spec_prefix=name, symbols={})
        if source.extends and source.describes:
            parent = self._units.get(source.extends)
            if parent is not None and parent.compiled.source.describes is None:
                self._warn(
                    ctx,
                    (),
                    "extends-base",
                    f"application definition extends base class {source.extends}",
                )
        if base_name:
            if base_name not in self._units:
                self._error(
                    ctx,
                    (),
                    "unknown-extends",
                    f"parent class {base_name!r} does not exist",
                )
            elif base_name in self._in_progress:
                self._error(ctx, (), "cyclic-extends", f"cycle through {base_name}")
            else:
                base = self.resolve(base_name)
        scope = {
            **(self._symbols.get(base.class_, {}) if base else {}),
            **{symbol: name for symbol in source.symbols},
        }
        self._symbols[name] = scope
        symbols = sorted(scope)
        ctx = replace(ctx, symbols=scope)
        texts = self.docs.setdefault(name, {})
        if source.doc:
            texts[name] = source.doc
        for symbol, info in source.symbols.items():
            if info.doc:
                texts[f"{name}#{symbol}"] = info.doc
        children = self._merge(
            base.children if base else [], source.children, ctx, (), name
        )
        attributes = self._merge(
            base.attributes if base else [], source.attributes, ctx, (), name
        )
        undeclared = self._undeclared(
            base.undeclared if base else UndeclaredPerKind(), source.undeclared
        )
        return ResolvedClass(
            class_=name,
            category=source.category,
            status=unit.status,
            extends=source.extends,
            describes=source.describes,
            deprecated=source.deprecated,
            symbols=symbols,
            attributes=attributes,
            children=children,
            require=[*(base.require if base else []), *source.require],
            undeclared=undeclared,
            source=unit.compiled.file,
            via=sort_rows(source.via or []) if ctx.nxdl else [],
            provisional=sorted(set(source.provisional or []), key=lambda d: int(d[1:])),
        )

    @staticmethod
    def _undeclared(base: UndeclaredPerKind, own) -> UndeclaredPerKind:
        if own is None:
            return base.model_copy()
        if isinstance(own, str):
            return UndeclaredPerKind(group=own, dataset=own, attribute=own)
        return own.model_copy()

    # ----------------------------------------------------------------- members

    def _merge(
        self,
        inherited: list,
        own: dict,
        ctx: _Context,
        path: tuple[str, ...],
        group: str,
    ) -> list:
        """Inherited members in order, refined in place, then the new ones (§5.2)."""
        result = [m.model_copy(deep=True) for m in inherited]
        inherited_keys = {(m.id, self._form(m)) for m in result}
        written: set[tuple[str, str]] = set()
        for key, member in own.items():
            is_child = isinstance(member, SourceChild)
            member_id = (member.id or key) if is_child else key
            node = member.node if is_child else "attribute"
            member_path = (*path, key if is_child else "@" + key)
            doc_key = f"{group}/{key}" if is_child else f"{group}@{key}"
            form = form_of(node)
            if node == "link":
                form = self._link_form(member, member_id, result, ctx, member_path)
            identity = (member_id, form)
            if identity in written:
                self._error(
                    ctx,
                    member_path,
                    "duplicate-id",
                    f"{node} {member_id!r} declared twice",
                )
                continue
            written.add(identity)
            positions = {(m.id, self._form(m)): i for i, m in enumerate(result)}
            if identity in inherited_keys:
                if member.refines is not None:
                    self._error(
                        ctx,
                        member_path,
                        "refines-inherited-label",
                        f"{member_id!r} has the label of an inherited member and refines",
                    )
                position = positions[identity]
                result[position] = self._refine(
                    result[position], member, ctx, member_path, doc_key
                )
                continue
            refined = None
            if member.refines is not None:
                if (member.refines, form) in inherited_keys:
                    refined = result[positions[(member.refines, form)]]
                else:
                    self._error(
                        ctx,
                        member_path,
                        "unknown-refines",
                        f"{member_id!r} refines {member.refines!r}: no inherited "
                        f"{node} member has that label",
                    )
            elif ctx.nxdl and (
                member.name is None or isinstance(member.name, ExactName)
            ):
                inherited_members = [
                    m for m in result if (m.id, self._form(m)) in inherited_keys
                ]
                refined = self._name_fit(
                    inherited_members, member_id, member, node, ctx, member_path
                )
            if refined is None:
                new = self._declare(member, member_id, node, ctx, member_path, doc_key)
                result.append(new)
                continue
            new = self._refine(
                refined, member, ctx, member_path, doc_key, new_id=member_id
            )
            # right after the refined member and the members already refining it
            position = positions[(refined.id, form)] + 1
            while position < len(result) and _refines_chain(
                result, result[position], refined.id
            ):
                position += 1
            result.insert(position, new)
        return result

    def _form(self, member: _Member) -> str:
        """The form of a resolved member in an identity (§5.1)."""
        node = node_of(member)
        if node == "link":
            key = (member.declared_by, member.id, member.target or "")
            return self._link_forms.get(key, "dataset")
        return form_of(node)

    def _link_form(
        self, member, member_id: str, inherited: list, ctx: _Context, path
    ) -> str:
        """§5.1: a link member has the form of its target, resolved from the label
        path; ``dataset`` (with a warning) when it cannot be resolved."""
        target = member.target
        if target is None:  # a refinement keeps the inherited target
            for candidate in inherited:
                if candidate.id == member_id and node_of(candidate) == "link":
                    return self._form(candidate)
            return "dataset"
        form = self._target_form(target, ctx)
        if form is None:
            self._warn(
                ctx,
                path,
                "unresolved-target",
                f"link {member_id!r}: target {target!r} does not resolve; form dataset",
            )
            self._unresolved.add((ctx.owner, member_id, target))
            form = "dataset"
        self._link_forms[(ctx.owner, member_id, target)] = form
        return form

    def _target_form(self, target: str, ctx: _Context) -> str | None:
        """The form of what a label path reaches, from the class being resolved
        (its source and its resolved parent) or, with a leading ``/``, the root."""
        if target.startswith("/"):
            found = self.resolve_target(None, target)
            return self._form(found) if found is not None else None
        source = ctx.unit.compiled.source
        base_name = source.extends or source.describes
        frame = self._classes.get(base_name) if base_name else None
        written: dict = source.children
        steps = target.split("/")
        for index, text in enumerate(steps):
            step, kind = label_step(text)
            last = index == len(steps) - 1
            own = None
            for key, candidate in (written or {}).items():
                label = candidate.id or key.split("[", 1)[0]
                fits = label == step or candidate.refines == step
                if not fits and candidate.node == "group" and candidate.class_:
                    # a step written as a class (T10) fits a group of that class
                    fits = t2_id(candidate.class_) == step
                if not fits or (kind and form_of(candidate.node) != kind):
                    continue
                if last or candidate.node == "group":
                    own = candidate
                    break
            found = None
            if frame is not None:
                kinds = ("group",) if not last else ("group", "dataset", "link")
                matches = [
                    c
                    for c in frame.children
                    if c.node in kinds
                    and (c.id == step or _refines_chain(frame.children, c, step))
                ]
                found = matches[0] if matches else None
            if last:
                node = own.node if own is not None else (found and found.node)
                if not node:
                    return None
                return "dataset" if node == "link" else form_of(node)
            if own is None and found is None:
                return None
            written = own.children if own is not None else {}
            if found is not None:
                frame = self._frame(found)
            elif own is not None and own.class_ not in self._in_progress:
                frame = self._classes.get(own.class_ or "")
            else:
                frame = None
        return None

    def _name_fit(
        self,
        candidates: list,
        member_id: str,
        member,
        node: str,
        ctx: _Context,
        path: tuple[str, ...],
    ):
        """The inherited free-named member an exact name refines (T18)."""
        name = member.name.exact if isinstance(member.name, ExactName) else member_id
        scored = []
        for candidate in candidates:
            if form_of(node_of(candidate)) != form_of(node):
                continue
            kind = name_kind(candidate.name)
            if kind not in ("template", "any") or not self.matches(
                candidate.name, name
            ):
                continue
            if node == "group":
                own_class = member.class_ or candidate.class_
                if (
                    candidate.class_
                    and own_class
                    and not self.is_subclass(own_class, candidate.class_)
                ):
                    continue
            score = (
                (2, fixed_characters(candidate.name.template))
                if kind == "template"
                else (1, 0)
            )
            scored.append((score, candidate))
        if not scored:
            return None
        best = max(score for score, _ in scored)
        winners = [c for score, c in scored if score == best]
        if len(winners) > 1:
            self._warn(
                ctx,
                path,
                "ambiguous-name-fit",
                f"{name!r} fits {', '.join(c.id for c in winners)}; refining {winners[0].id}",
            )
        return winners[0]

    def _shape(
        self, shape: Shape | None, ctx: _Context, path: tuple[str, ...]
    ) -> ResolvedShape | None:
        if shape is None:
            return None
        result = ResolvedShape(**shape.model_dump(exclude_none=True))
        if result.binding is None:
            result.binding = ctx.unit.compiled.source.defaults.binding
        for symbol in _shape_symbols(result):
            declared_by = ctx.symbols.get(symbol)
            if declared_by is None:
                self._warn(
                    ctx, path, "undeclared-symbol", f"symbol {symbol!r} is not declared"
                )
                declared_by = ctx.owner
            result.symbols[symbol] = declared_by
        return result

    def _record_docs(
        self, member, ctx: _Context, doc_key: str
    ) -> tuple[list[str], Enumeration | None]:
        """Move documentation texts to the store; the enumeration without docs."""
        texts = self.docs.setdefault(ctx.owner, {})
        keys = []
        if member.doc:
            texts[doc_key] = member.doc
            keys.append(doc_key)
        enum = member.enum
        if enum is not None and any(v.doc for v in enum.values):
            for value in enum.values:
                if value.doc:
                    texts[f"{doc_key}={value.value}"] = value.doc
            enum = enum.model_copy(
                update={
                    "values": [v.model_copy(update={"doc": None}) for v in enum.values]
                }
            )
        return keys, enum

    def _declare(
        self,
        member,
        member_id: str,
        node: str,
        ctx: _Context,
        path: tuple[str, ...],
        doc_key: str,
    ) -> _Member:
        defaults = ctx.unit.compiled.source.defaults
        name = member.name or ExactName(exact=member_id)
        kind = name_kind(name)
        via = set(member.via or [])
        provisional = set(member.provisional or [])
        written = member.occurs
        min_value = written.min if written and written.min is not None else defaults.min
        if written and written.max is not None:
            max_value = written.max
        else:
            max_value = 1 if kind in ("exact", "ref") else "unbounded"
            provisional.add("Q1")
        if kind == "template":
            provisional.add("Q3")
        if member.shape is not None and member.shape.binding is None:
            provisional.add("Q5")
        type_name = member.type
        if node in ("dataset", "attribute") and type_name is None:
            type_name = defaults.type or _DEFAULT_TYPE
        doc_keys, enum = self._record_docs(member, ctx, doc_key)
        common = dict(
            id=member_id,
            name=name,
            occurs=ResolvedOccurs(min=min_value, max=max_value),
            recommended=bool(member.recommended) and min_value == 0,
            type=type_name if node in ("dataset", "attribute") else None,
            shape=self._shape(member.shape, ctx, path),
            units=member.units,
            enum=enum,
            length=member.length,
            rank=member.rank,
            names_child=member.names_child,
            deprecated=member.deprecated,
            docs=doc_keys,
            show=member.show,
            declared_by=ctx.owner,
        )
        self._check_occurs(
            SimpleNamespace(id=member_id, name=name, occurs=common["occurs"]),
            member,
            ctx,
            path,
        )
        if enum is not None and ctx.nxdl:
            common["enum"] = self._typed_enum(
                SimpleNamespace(enum=enum, type=common["type"], shape=common["shape"]),
                ctx,
                path,
            )
        if not ctx.nxdl:
            via = set()
        if node == "attribute":
            return ResolvedAttribute(
                **common, provisional=_decisions(provisional), via=sort_rows(via)
            )
        if node == "link":
            provisional.add("Q8")
        if node == "group" and not member.class_:
            self._error(ctx, path, "missing-class", f"group {member_id!r} has no class")
        result = ResolvedChild(
            **common,
            node=node,
            class_=member.class_ if node == "group" else None,
            target=member.target,
            attributes=(
                self._merge([], member.attributes, ctx, path, doc_key)
                if node != "group"
                else []
            ),
            provisional=_decisions(provisional),
            via=sort_rows(via),
        )
        if node == "group":
            if member.class_ and member.class_ not in self._units:
                self._error(
                    ctx,
                    path,
                    "unknown-class",
                    f"class {member.class_!r} does not exist",
                )
            self._specialise(result, member, None, ctx, path)
        return result

    def _refine(
        self,
        parent: _Member,
        member,
        ctx: _Context,
        path: tuple[str, ...],
        doc_key: str,
        new_id: str | None = None,
    ) -> _Member:
        defaults = ctx.unit.compiled.source.defaults
        doc_keys, enum = self._record_docs(member, ctx, doc_key)
        result = parent.model_copy(deep=True)
        via = set(parent.via) | set(member.via or [])
        provisional = set(parent.provisional) | set(member.provisional or [])
        if new_id is not None:
            result.id = new_id
            result.name = member.name or ExactName(exact=new_id)
            result.refines = parent.id
            result.declared_by = ctx.owner
            result.refined_by = []
            if isinstance(result.name, ExactName) and not (
                member.occurs and member.occurs.max is not None
            ):
                # §3.1: an exact name refining a free one; defaulted, so never wider
                inherited = parent.occurs.max
                result.occurs.max = 1 if inherited == "unbounded" else min(1, inherited)
            if member.refines is None:
                via.add("T18")
                provisional.add("Q4")
        elif member.name is not None:
            result.name = member.name
        elif ctx.nxdl and not isinstance(parent.name, RefName):
            # T0: an NXDL name without nameType is exact (the XSD default); an NXDS
            # refinement that states no name keeps the inherited one (§5.2)
            result.name = ExactName(exact=parent.id)
        written = member.occurs
        if written and written.min is not None:
            if written.min < parent.occurs.min:
                self._warn(
                    ctx,
                    path,
                    "widened-occurs",
                    f"{result.id!r}: min {written.min} < inherited {parent.occurs.min}",
                )
            result.occurs.min = written.min
        else:
            result.occurs.min = max(defaults.min, parent.occurs.min)
        if written and written.max is not None:
            if parent.occurs.max != "unbounded" and (
                written.max == "unbounded" or written.max > parent.occurs.max
            ):
                self._warn(
                    ctx,
                    path,
                    "widened-occurs",
                    f"{result.id!r}: max {written.max} > inherited {parent.occurs.max}",
                )
            result.occurs.max = written.max
        if member.recommended is not None:
            result.recommended = member.recommended
        self._check_occurs(result, member, ctx, path)
        result.recommended = result.recommended and result.occurs.min == 0
        if member.type is not None and member.type != parent.type:
            if parent.type is not None and not self._facts.is_narrower(
                member.type, parent.type
            ):
                self._warn(
                    ctx,
                    path,
                    "type-not-narrower",
                    f"{result.id!r}: {member.type} is not narrower than {parent.type}",
                )
            result.type = member.type
        if member.enum is not None:
            result.enum = enum
        if member.shape is not None:
            result.shape = self._shape(member.shape, ctx, path)
            if member.shape.binding is None:
                provisional.add("Q5")
        for key in ("units", "length", "rank", "names_child", "deprecated", "show"):
            value = getattr(member, key)
            if value is not None:
                setattr(result, key, value)
        if doc_keys:
            result.docs = [*result.docs, *doc_keys]
        if ctx.owner != result.declared_by and ctx.owner not in result.refined_by:
            result.refined_by = [*result.refined_by, ctx.owner]
        if isinstance(result, ResolvedChild):
            if isinstance(member, SourceChild):
                # a link member refines an inherited dataset member (§5.1)
                result.node = member.node
                if member.class_ and member.class_ != parent.class_:
                    if parent.class_ and not self.is_subclass(
                        member.class_, parent.class_
                    ):
                        self._warn(
                            ctx,
                            path,
                            "class-not-subclass",
                            f"{result.id!r}: {member.class_} is not a subclass of {parent.class_}",
                        )
                    result.class_ = member.class_
                if member.target is not None:
                    result.target = member.target
                if result.node != "group":
                    result.attributes = self._merge(
                        parent.attributes, member.attributes, ctx, path, doc_key
                    )
            if result.node == "link":
                provisional.add("Q8")
            if result.node == "group":
                self._specialise(result, member, parent, ctx, path)
        if member.enum is not None:
            result.enum = self._typed_enum(result, ctx, path)
            if parent.enum is not None and not parent.enum.open:
                allowed = {_hashable(v.value) for v in parent.enum.values}
                if not {_hashable(v.value) for v in result.enum.values} <= allowed:
                    if result.id == self._profile.dispatch_dataset:
                        via.add("T8b")
                    else:
                        self._warn(
                            ctx,
                            path,
                            "enum-not-subset",
                            f"{result.id!r}: enumeration is not a subset of the inherited one",
                        )
        result.via = sort_rows(via) if ctx.nxdl else []
        result.provisional = _decisions(provisional)
        return result

    def _typed_enum(self, result, ctx: _Context, path) -> Enumeration | None:
        """§5.2.7: values of NXDL sources typed with the resolved type and shape."""
        if result.enum is None or not ctx.nxdl:
            return result.enum
        enum, bad = typed_enum(
            result.enum, result.type, result.shape, self._facts.types
        )
        for text in bad:
            self._warn(
                ctx, path, "enum-value-type", f"item {text!r} is not a {result.type}"
            )
        return enum

    def _check_occurs(self, result: _Member, member, ctx: _Context, path) -> None:
        """Resolution warnings of §3.1 and §4.1 about what a member states."""
        written = member.occurs
        if (
            isinstance(result.name, ExactName)
            and written is not None
            and written.max is not None
            and (written.max == "unbounded" or written.max > 1)
        ):
            self._warn(
                ctx,
                path,
                "exact-max",
                f"{result.id!r}: an exact name occurs at most once, max {written.max}",
            )
        if member.recommended and result.occurs.min >= 1:
            self._warn(
                ctx,
                path,
                "recommended-required",
                f"{result.id!r}: recommended has no effect with min {result.occurs.min}",
            )

    def _specialise(
        self,
        result: ResolvedChild,
        member,
        parent,
        ctx: _Context,
        path: tuple[str, ...],
    ) -> None:
        """A group with content of its own becomes a specialisation."""
        if not isinstance(member, SourceChild):
            return
        has_content = bool(
            member.children
            or member.attributes
            or member.require
            or member.undeclared is not None
        )
        inherited_spec = None
        if (
            parent is not None
            and parent.specialisation
            and parent.class_ == result.class_
        ):
            inherited_spec = self._specs.get(parent.specialisation)
        if not has_content:
            if inherited_spec is None:
                result.specialisation = None
            return
        spec_id = f"{ctx.spec_prefix}/{result.id}"
        base = inherited_spec or self._class_for(result.class_, ctx, path)
        base_class = base.class_ if base is not None else None
        sub = replace(
            ctx,
            spec_prefix=spec_id,
            symbols={**self._symbols.get(base_class or "", {}), **ctx.symbols},
        )
        children = self._merge(
            base.children if base else [], member.children, sub, path, spec_id
        )
        attributes = self._merge(
            base.attributes if base else [], member.attributes, sub, path, spec_id
        )
        spec = Specialisation(
            id=spec_id,
            class_=result.class_ or "",
            declared_by=ctx.owner,
            attributes=attributes,
            children=children,
            require=[*(base.require if base else []), *member.require],
            undeclared=self._undeclared(
                base.undeclared if base else UndeclaredPerKind(), member.undeclared
            ),
        )
        self._specs[spec_id] = spec
        if base is not None:
            self._spec_base[spec_id] = (
                base.id if isinstance(base, Specialisation) else base.class_
            )
        result.specialisation = spec_id

    # ------------------------------------------------------------------ checks

    def _frame(self, member: ResolvedChild):
        if member.specialisation and member.specialisation in self._specs:
            return self._specs[member.specialisation]
        return self._classes.get(member.class_ or "")

    def resolve_target(
        self, root, target: str, node: str | None = None
    ) -> ResolvedChild | None:
        """The member reached by a label path from a class or specialisation (§4.6).

        A step matches a member with that label or one that refines it; a path
        starting with ``/`` starts at the root class.
        """
        if target.startswith("/"):
            root = self._classes.get(self._profile.root_class)
            target = target[1:]
        return self._walk(root, target.split("/"), node)

    def _walk(self, frame, steps: list[str], node: str | None):
        if frame is None or not steps:
            return None
        step, kind = label_step(steps[0])
        last = len(steps) == 1
        kinds = ("group", "dataset", "link")
        if last and node:
            kinds = (node,)
        if not last:
            kinds = ("group",)
        if kind is not None:
            kinds = tuple(k for k in kinds if form_of(k) == kind)
        children = [c for c in frame.children if c.node in kinds]
        candidates = sorted(
            (
                c
                for c in children
                if c.id == step or _refines_chain(frame.children, c, step)
            ),
            key=lambda c: c.id != step,
        )
        for candidate in candidates:
            if last:
                return candidate
            found = self._walk(self._frame(candidate), steps[1:], node)
            if found is not None:
                return found
        return None

    def _check_links(
        self, name: str, resolved: ResolvedClass, specs: dict[str, Specialisation]
    ) -> None:
        unit = self._units[name]
        ctx = _Context(owner=name, unit=unit, spec_prefix=name, symbols={})
        for group_id, group in [(name, resolved), *specs.items()]:
            for member in group.children:
                if member.node != "link" or not member.target:
                    continue
                if member.declared_by != name and name not in member.refined_by:
                    continue
                if (name, member.id, member.target) in self._unresolved:
                    continue  # reported when its form was resolved
                if self.resolve_target(resolved, member.target) is None:
                    path = tuple(group_id.split("/")[1:]) + (member.id,)
                    self._warn(
                        ctx,
                        path,
                        "unresolved-target",
                        f"link {member.id!r}: target {member.target!r} does not resolve",
                    )

    def _check_require(
        self, name: str, resolved: ResolvedClass, specs: dict[str, Specialisation]
    ) -> None:
        unit = self._units[name]
        ctx = _Context(owner=name, unit=unit, spec_prefix=name, symbols={})
        for group_id, group in [(name, resolved), *specs.items()]:
            ids = {m.id for m in group.children}
            for constraint in group.require:
                kind, members = constraint_kind(constraint)
                missing = [m for m in members if m not in ids]
                if missing:
                    path = tuple(group_id.split("/")[1:])
                    self._error(
                        ctx,
                        path,
                        "unknown-constraint-member",
                        f"{kind} names unknown members {missing}",
                    )

    # --------------------------------------------------------------- compaction

    def group(self, group_id: str) -> ResolvedClass | Specialisation | None:
        """A resolved class or specialisation by id."""
        if "/" in group_id:
            return self._specs.get(group_id)
        return self._classes.get(group_id)

    def _base_of(self, group_id: str) -> str | None:
        if "/" in group_id:
            return self._spec_base.get(group_id)
        resolved = self._classes.get(group_id)
        if resolved is None:
            return None
        base = resolved.extends or resolved.describes
        return base if base in self._classes else None

    def _canonical(self, group_id: str, member: _Member) -> str:
        """The group where this exact member is listed in full, nearest the root."""
        node = node_of(member)
        key = (group_id, member.id, node)
        if key in self._homes:
            return self._homes[key]
        result = group_id
        base_id = self._base_of(group_id)
        base = self.group(base_id) if base_id else None
        if base is not None:
            members = base.attributes if node == "attribute" else base.children
            for candidate in members:
                if candidate.id == member.id and node_of(candidate) == node:
                    if candidate == member:
                        result = self._canonical(base_id, candidate)
                    break
        self._homes[key] = result
        return result

    def _compact_members(self, group_id: str, members: list) -> list:
        result = []
        for member in members:
            home = self._canonical(group_id, member)
            if home == group_id:
                result.append(member)
            elif isinstance(member, ResolvedChild):
                result.append(MemberRef(ref=f"{home}/{member.id}", node=member.node))
            else:
                result.append(MemberRef(ref=f"{home}@{member.id}"))
        return result

    def compact(self, document: ResolvedDocument) -> ResolvedDocument:
        """The document with members listed in full only where they change."""
        name = document.definition.class_
        definition = document.definition.model_copy(
            update={
                "children": self._compact_members(name, document.definition.children),
                "attributes": self._compact_members(
                    name, document.definition.attributes
                ),
            }
        )
        specs = {
            spec_id: spec.model_copy(
                update={
                    "children": self._compact_members(spec_id, spec.children),
                    "attributes": self._compact_members(spec_id, spec.attributes),
                }
            )
            for spec_id, spec in document.specialisations.items()
        }
        return ResolvedDocument(
            requires=document.requires, definition=definition, specialisations=specs
        )

    # ------------------------------------------------------------------ bundle

    def index(self, release: str, documents: dict[str, ResolvedDocument]) -> Index:
        """The bundle without its documents."""
        features = sorted({f for d in documents.values() for f in d.requires})
        return Index(
            release=release,
            features=features,
            decisions=DECISIONS,
            statuses=STATUSES,
            types=self._facts.types,
            units=self._facts.units,
            names=self._facts.names,
            unit_symbols=unit_symbols(),
            profiles={self._profile.name: self._profile},
            codes=load_codes(),
            classes={
                n: ClassEntry(
                    category=d.definition.category,
                    status=d.definition.status,
                    extends=d.definition.extends,
                    describes=d.definition.describes,
                    specialisations=len(d.specialisations),
                )
                for n, d in sorted(documents.items())
            },
        )

    def bundle(self, release: str, documents: dict[str, ResolvedDocument]) -> Bundle:
        """Everything a validator needs, in one object (members by reference)."""
        index = self.index(release, documents)
        return Bundle(
            **dict(index),
            documents={n: self.compact(d) for n, d in sorted(documents.items())},
        )


def _hashable(value):
    return tuple(value) if isinstance(value, list) else value


def _decisions(decisions: set[str]) -> list[str]:
    return sorted(decisions, key=lambda d: int(d[1:]))


def _shape_symbols(shape: Shape) -> list[str]:
    symbols = []
    if isinstance(shape.rank, str):
        symbols.extend(_IDENTIFIER.findall(shape.rank))
    elif isinstance(shape.rank, DimExpr):
        symbols.extend(_IDENTIFIER.findall(shape.rank.expr))
    for dim in shape.dims or []:
        if isinstance(dim, OptionalDim):
            dim = dim.value
        if isinstance(dim, str):
            symbols.append(dim)
        elif isinstance(dim, DimExpr):
            symbols.extend(
                _IDENTIFIER.findall(re.sub(r"(\d)([A-Za-z_])", r"\1*\2", dim.expr))
            )
    return symbols


#: language features outside the core of this version (§6.4): none in 0.1
FEATURES: frozenset[str] = frozenset()


def features_of(groups: list) -> list[str]:
    """The language features outside the core (§6.4) that groups use: none in 0.1."""
    del groups
    return []


def _refines_chain(members: list, member, label: str) -> bool:
    """Whether ``member`` refines the member ``label`` (directly or through others)."""
    by_id = {(m.id, form_of(node_of(m))): m for m in members}
    node = form_of(node_of(member))
    seen = set()
    while member is not None and member.refines and member.refines not in seen:
        if member.refines == label:
            return True
        seen.add(member.refines)
        member = by_id.get((member.refines, node))
    return False


def symbols_of(shape: Shape) -> list[str]:
    """The symbols a shape refers to."""
    return _shape_symbols(shape)
