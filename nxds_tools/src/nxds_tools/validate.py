"""A lazy HDF5 validator driven by the bundle (spec §7–§12; tiers M and S).

The file is walked one group at a time; only metadata and one-element datasets
are read, and findings are yielded as soon as a group is done.
"""

import ast
import json
import re
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ._units import UnitsError
from ._units import dimensions
from ._units import normalise
from .bundle import BundleReader
from .model import Bundle
from .model import DimExpr
from .model import ExactName
from .model import Finding
from .model import OptionalDim
from .model import RankOf
from .model import RefName
from .model import ResolvedAttribute
from .model import ResolvedChild
from .model import StorageProfile
from .model import TemplateName
from .model import UndeclaredPerKind
from .model import UnitsCategory
from .model import constraint_kind
from .resolve import FEATURES
from .resolve import fixed_characters
from .resolve import form_of
from .resolve import label_step
from .resolve import template_regex


def validate(
    file: Path | str,
    bundle: "Bundle | BundleReader | Path | str",
    expect: str | None = None,
    partial: bool = False,
    profile: str = "hdf5",
) -> Iterator[Finding]:
    """Validate a file; each finding is yielded as soon as it is known.

    ``bundle`` is a bundle, a reader, or the path of a bundle file or of a
    generated directory (read lazily).
    """
    if isinstance(bundle, Bundle):
        reader, owned = BundleReader.from_bundle(bundle), True
    elif isinstance(bundle, BundleReader):
        reader, owned = bundle, False
    else:
        reader, owned = BundleReader.open(bundle), True
    try:
        handle = _open(Path(file))
        try:
            validator = _Validator(
                reader, reader.index.profiles[profile], expect, partial
            )
            yield from validator.run(handle)
        finally:
            handle.close()
    finally:
        if owned:
            reader.close()


def file_release(file: Path | str, attribute: str) -> str | None:
    """The release a file names (the profile's release attribute on the root),
    if any (§12.3)."""
    with _open(Path(file)) as handle:
        value = handle.attrs.get(attribute)
    return str(_text(value)) if value is not None else None


def finding_json(finding: Finding) -> str:
    """One finding as one line of JSON (spec §10.1)."""
    data = finding.model_dump(exclude_none=True)
    data.setdefault("member", None)
    return json.dumps(data, ensure_ascii=False)


def finding_text(finding: Finding) -> str:
    """One line for people: severity, place in the file, what is wrong."""
    words = {"E": "ERROR", "W": "WARNING", "I": "INFO"}
    line = (
        f"{words.get(finding.severity, finding.severity):7} {finding.path}: "
        f"{_DESCRIPTIONS.get(finding.code, finding.code)}"
    )
    if finding.member:
        line += f" ({finding.member})"
    if finding.message:
        line += f" — {finding.message}"
    return line


def sort_key(finding: Finding) -> tuple:
    """Findings in a stable order: path, code, member."""
    return finding.path, finding.code, finding.member or "", finding.message or ""


_DESCRIPTIONS: dict[str, str] = {
    "MISSING": "a required item is missing",
    "TOO-MANY": "more items than allowed",
    "CLASS": "the group has the wrong class",
    "NO-CLASS": "the group has no class",
    "TYPE": "wrong data type",
    "SHAPE": "wrong shape",
    "ENUM": "value not allowed",
    "ENUM-OPEN": "value not in the list of suggested values",
    "REF": "names an item that does not exist",
    "CONSTRAINT": "a rule between items fails",
    "LINK": "the link points to nothing or to the wrong item",
    "RECOMMENDED": "a recommended item is missing",
    "DEPRECATED": "a deprecated item is used",
    "UNITS": "units missing or of the wrong kind",
    "NAME": "the name is not allowed",
    "UNDECLARED": "not declared by any class (allowed)",
    "INCOMPLETE": "not finished yet (partial mode)",
    "SKIPPED": "check not done",
    "BUNDLE": "release used",
    "NO-DEFINITION": "no entry follows an application definition",
    "UNKNOWN-DEFINITION": "unknown application definition",
    "UNKNOWN-CLASS": "unknown class",
    "UNKNOWN-RELEASE": "unknown NeXus release",
}

_DATE_TIME = re.compile(
    r"-?(\d{4,})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})?"
)
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def _open(path: Path) -> h5py.File:
    """Open read-only, in SWMR mode when the file allows it (§11)."""
    try:
        return h5py.File(path, "r", swmr=True)
    except (OSError, ValueError):
        return h5py.File(path, "r")


# --------------------------------------------------------------------- state


@dataclass
class _Frame:
    """The member list that applies to a group: a class or a specialisation."""

    scope: str
    #: the class of the members (of the specialised member for a specialisation)
    nx_class: str
    #: the application definition the members belong to, if any
    app: str | None
    children: list[ResolvedChild]
    attributes: list[ResolvedAttribute]
    require: list
    undeclared: UndeclaredPerKind
    #: labels shared by a group and a dataset member (written with a kind suffix)
    ambiguous: set[str] = field(default_factory=set)
    #: the class is not in the bundle: content undeclared, not walked further
    unknown: bool = False


@dataclass
class _Object:
    """An entry of a group: a group, a dataset or a link."""

    name: str
    path: str
    #: group or dataset; ``None`` for a dangling link or an unreadable object
    kind: str | None
    #: soft, external, hard (another path of an object with a target attribute)
    link: str | None
    obj: Any = None
    nx_class: str | None = None
    identity: tuple[str, int] | None = None
    #: whether the object is walked here (its own path, §9.8)
    own: bool = True
    #: the application definition the group is dispatched to (or counts as)
    dispatch: str | None = None
    #: the dispatch member it is checked against (dispatched by its own definition)
    dispatch_member: ResolvedChild | None = None
    #: a soft link's target path in the same file
    target: str | None = None


@dataclass(frozen=True)
class _Use:
    """One binding use of a symbol (§9.3)."""

    value: int
    path: str
    growable: bool


@dataclass
class _Entry:
    """An instance of the outermost dispatched group (or the file): symbols (§9.3)."""

    path: str
    stopped: bool = False
    values: dict[tuple[str, str], list[_Use]] = field(default_factory=dict)
    expressions: list[tuple[str, dict[str, str], _Use]] = field(default_factory=list)


#: one step of the chain of a group: the labels it is assigned to, its path
_Step = tuple[frozenset[str], str]


@dataclass
class _Task:
    """A group to walk, or a function to call once a subtree is done."""

    group: Any = None
    path: str = "/"
    frame: _Frame | None = None
    entry: _Entry | None = None
    chain: tuple[_Step, ...] = ()
    #: depth of the first step of label paths of an application definition
    base: int = 1
    #: reached through a link: only the members of a specialisation are applied
    linked: bool = False
    #: the application definition the walk is in (§8.3)
    app: str | None = None
    #: the group's own class when it is a subclass of the frame's class (§8.7)
    own: _Frame | None = None
    post: Callable[[], None] | None = None


@dataclass
class _LinkCheck:
    path: str
    member: str
    identity: tuple[str, int]
    chain: tuple[_Step, ...]
    base: int
    steps: list[str]
    #: the target's own path, when it was walked before the link (re-derived)
    earlier: str | None = None


# ----------------------------------------------------------------- validator


class _Validator:
    def __init__(
        self,
        reader: BundleReader,
        profile: StorageProfile,
        expect: str | None,
        partial: bool,
    ) -> None:
        self.reader = reader
        self.index = index = reader.index
        self.profile = profile
        self.expect = expect
        self.partial = partial
        self._label = f"{index.release}-r{index.revision}"
        self._pending: list[Finding] = []
        self._seen: set[Finding] = set()
        self._quiet = False
        self._item_re = re.compile(index.names.item_pattern)
        self._max_length = index.names.item_max_length
        self._templates: dict[str, re.Pattern] = {}
        self._frames: dict[str, _Frame | None] = {}
        self._restricted: dict[str, frozenset[str]] = {}
        self._walked: set[tuple[str, int]] = set()
        #: object with several hard paths → (own path, has a target attribute)
        self._own_paths: dict[tuple[str, int], tuple[str, bool]] = {}
        #: file → address → hard paths, only for objects with several paths
        self._scans: dict[str, dict[int, list[str]]] = {}
        #: link target → the chains it is assigned with (only targets of links)
        self._assigned: dict[tuple[str, int], list[tuple[_Step, ...]]] = {}
        #: object of another file → the path it was first checked at
        self._external: dict[tuple[str, int], str] = {}
        self._links: list[_LinkCheck] = []
        #: groups dispatched by their own definition: (definition, class)
        self._dispatched: list[tuple[str, str | None]] = []
        self._skipped_members: set[str] = set()
        self._profile_attributes = {
            profile.class_attribute,
            profile.units_attribute,
            profile.link_target_attribute,
            profile.release_attribute,
        }

    # -------------------------------------------------------------- findings

    def _add(
        self,
        code: str,
        path: str,
        member: str | None,
        message: str | None = None,
        exception: str | None = None,
        condition: str | None = None,
    ) -> None:
        """A finding; severity, its exceptions and the partial-mode rule come
        from the index (§10.3, §11)."""
        if self._quiet:
            return
        known = self.index.codes.get(code)
        severity = known.severity if known is not None else "E"
        if known is not None and exception in known.exceptions:
            severity = known.exceptions[exception]
        if self.partial and known is not None:
            rule = known.partial
            if rule == "always" or (condition is not None and rule == condition):
                message = f"{code}: {message}" if message else code
                code = "INCOMPLETE"
                severity = self.index.codes[code].severity
        finding = Finding(
            code=code,
            severity=severity,
            path=path,
            member=member,
            bundle=self._label,
            message=message,
        )
        if finding not in self._seen:
            self._seen.add(finding)
            self._pending.append(finding)

    def _flush(self) -> Iterator[Finding]:
        """The findings of one group: duplicates are removed per group."""
        pending, self._pending = self._pending, []
        self._seen.clear()
        yield from pending

    # ------------------------------------------------------------------ run

    def run(self, handle: h5py.File) -> Iterator[Finding]:
        self._root = handle
        self._release(handle)
        yield from self._flush()
        frame = self._class_frame(self.profile.root_class) or _empty_frame("")
        root_entry = _Entry("/")
        self._walked.add(self._identity(handle["/"]) or ("", 0))
        stack = [_Task(handle, "/", frame, root_entry, ((frozenset(), "/"),))]
        while stack:
            task = stack.pop()
            try:
                if task.post is not None:
                    task.post()
                else:
                    stack.extend(reversed(self._group(task)))
            except Exception as exc:  # a read error never stops the validation
                self._add("SKIPPED", task.path, None, f"cannot read: {_error(exc)}")
            yield from self._flush()
        for step in (
            lambda: self._symbols(root_entry),
            self._check_links,
            self._root_level,
            self._no_definition,
        ):
            try:
                step()
            except Exception as exc:
                self._add("SKIPPED", "/", None, f"cannot check: {_error(exc)}")
            yield from self._flush()

    def _release(self, handle: h5py.File) -> None:
        name = self.profile.release_attribute
        try:
            release = handle.attrs.get(name)
        except Exception as exc:
            self._add("SKIPPED", _attribute_path("/", name), None, _error(exc))
            return
        if release is None:
            self._add("BUNDLE", "/", None, f"no {name}: using {self.index.release}")
            return
        text = str(_text(release))
        wanted = self.index.release.removeprefix("v").split(".post")[0]
        if text.removeprefix("v").split(".post")[0] != wanted:
            self._add(
                "UNKNOWN-RELEASE",
                "/",
                None,
                f"file names {text}, using {self.index.release}",
            )

    # ----------------------------------------------------------- own paths

    def _own_path(self, obj: Any, identity: tuple[str, int], path: str):
        """The own path of an object with several hard paths, and whether its
        target attribute names it (§9.8, §12.1)."""
        if identity in self._own_paths:
            return self._own_paths[identity]
        result = None
        try:
            value = obj.attrs.get(self.profile.link_target_attribute)
            target = _text(value) if value is not None else None
            if isinstance(target, str) and target.startswith("/"):
                found = obj.file.get(target)
                if found is not None and self._identity(found) == identity:
                    result = (target, True)
        except Exception:
            result = None
        if result is None:
            paths = self._scan(obj.file).get(identity[1], [path])
            result = (min(paths, key=_utf8), False)
        self._own_paths[identity] = result
        return result

    def _scan(self, handle: h5py.File) -> dict[int, list[str]]:
        """The hard paths of the objects of a file that have several (once per
        file; nothing is kept for the others)."""
        name = handle.filename
        if name in self._scans:
            return self._scans[name]
        paths: dict[int, list[str]] = {}
        stack: list[tuple[h5py.Group, str]] = [(handle["/"], "/")]
        while stack:
            group, path = stack.pop()
            try:
                names = list(group.keys())
            except Exception:
                continue
            for child in names:
                try:
                    link = group.id.links.get_info(child.encode())
                    if link.type != h5py.h5l.TYPE_HARD:
                        continue
                    info = h5py.h5o.get_info(group.id, child.encode())
                    child_path = _join(path, child)
                    if info.rc > 1:
                        seen = info.addr in paths
                        paths.setdefault(info.addr, []).append(child_path)
                        if seen:
                            continue
                    if info.type == h5py.h5o.TYPE_GROUP:
                        stack.append((group[child], child_path))
                except Exception:
                    continue
        self._scans[name] = paths
        return paths

    # -------------------------------------------------------------- frames

    def _is_app(self, name: str | None) -> bool:
        """An application definition: a class with ``describes`` (§3)."""
        entry = self.index.classes.get(name or "")
        return entry is not None and entry.describes is not None

    def _make_frame(self, group_id: str) -> _Frame | None:
        if group_id not in self._frames:
            group = self.reader.group(group_id)
            frame = None
            document = self.reader.document(group_id.split("/", 1)[0])
            unknown = sorted(set(document.requires) - FEATURES) if document else []
            if unknown:
                # §6.4: never guess what an unknown feature means
                self._add(
                    "SKIPPED",
                    "/",
                    group_id,
                    f"unknown language features: {', '.join(unknown)}",
                )
                group = None
            if group is not None:
                app = group_id.split("/", 1)[0]
                forms: dict[str, set[str]] = {}
                for member in group.children:
                    if not isinstance(member.name, RefName):  # roles apart (§5.1)
                        forms.setdefault(member.id, set()).add(form_of(member.node))
                frame = _Frame(
                    scope=group_id,
                    nx_class=group.class_,
                    app=app if self._is_app(app) else None,
                    children=list(group.children),
                    attributes=list(group.attributes),
                    require=list(group.require),
                    undeclared=group.undeclared,
                    ambiguous={k for k, v in forms.items() if len(v) > 1},
                )
            self._frames[group_id] = frame
        return self._frames[group_id]

    def _class_frame(self, name: str | None) -> _Frame | None:
        if not name or name not in self.index.classes:
            return None
        return self._make_frame(name)

    def _member_frame(self, member: ResolvedChild | None, o: _Object) -> _Frame:
        """The frame of a group: the specialisation of its member, else its class."""
        if member is not None and member.specialisation:
            frame = self._make_frame(member.specialisation)
            if frame is not None:
                return frame
        return self._class_frame(o.nx_class) or _empty_frame(o.nx_class or "")

    def _leftovers(self, frame: _Frame, o: _Object) -> _Frame | None:
        """The group's own class when it is a subclass of the frame's (§8.7)."""
        if not o.nx_class or o.nx_class == frame.nx_class:
            return None
        if not self._is_subclass(o.nx_class, frame.nx_class):
            return None
        return self._class_frame(o.nx_class)

    def _is_subclass(self, name: str | None, parent: str | None) -> bool:
        seen = set()
        while name and name not in seen:
            if name == parent:
                return True
            seen.add(name)
            entry = self.index.classes.get(name)
            if entry is None:
                return False
            name = entry.extends or entry.describes
        return False

    def _extends(self, app: str | None, parent: str | None) -> bool:
        """Whether an application definition is ``parent`` or extends it."""
        seen = set()
        while app and app not in seen:
            if app == parent:
                return True
            seen.add(app)
            entry = self.index.classes.get(app)
            app = entry.extends if entry is not None else None
        return False

    def _ref(self, frame: _Frame, member: ResolvedChild) -> str:
        """The member reference (§10.2): a kind suffix only where labels are shared."""
        label = member.id
        if label in frame.ambiguous and not isinstance(member.name, RefName):
            label += f"[{form_of(member.node)}]"
        return f"{frame.scope}/{label}"

    def _labels(
        self, members: list, member: ResolvedChild | ResolvedAttribute | None
    ) -> frozenset[str]:
        """A member's label and the labels of the members it refines."""
        if member is None:
            return frozenset()
        form = form_of(getattr(member, "node", "attribute"))
        by_id = {(m.id, form_of(getattr(m, "node", "attribute"))): m for m in members}
        labels = {member.id}
        while member is not None and member.refines and member.refines not in labels:
            labels.add(member.refines)
            member = by_id.get((member.refines, form))
        return frozenset(labels)

    # ------------------------------------------------------------- matching

    def _matches(self, name: Any, value: str) -> bool:
        if isinstance(name, ExactName):
            return name.exact == value
        if isinstance(name, TemplateName):
            regex = self._templates.get(name.template)
            if regex is None:
                regex = self._templates[name.template] = template_regex(
                    name.template, self.profile.placeholder_characters
                )
            return regex.fullmatch(value) is not None
        if isinstance(name, RefName):
            return False
        return self._valid_name(value)

    def _valid_name(self, value: str) -> bool:
        if self._max_length is not None and len(value) > self._max_length:
            return False
        return self._item_re.fullmatch(value) is not None

    @staticmethod
    def _priority(members: list, index: int, link: bool = False) -> tuple:
        """Choice keys (§7.3): exact, template, any; fixed characters; refines;
        a link member for a link; order."""
        member = members[index]
        rank = {ExactName: 0, TemplateName: 1}.get(type(member.name), 2)
        fixed = (
            fixed_characters(member.name.template)
            if isinstance(member.name, TemplateName)
            else 0
        )
        depth = 0
        form = form_of(getattr(member, "node", "attribute"))
        by_id = {(m.id, form_of(getattr(m, "node", "attribute"))): m for m in members}
        current = member
        while current is not None and current.refines and depth < 50:
            depth += 1
            current = by_id.get((current.refines, form))
        not_link = link and getattr(member, "node", None) != "link"
        return rank, -fixed, -depth, not_link, index

    def _is_dispatch(self, member: ResolvedChild, frame: _Frame) -> bool:
        """A member an application definition declares or refines whose class is
        an entry point (§8.3)."""
        return (
            frame.app is not None
            and member.node == "group"
            and member.class_ in self.profile.entry_points
            and any(self._is_app(c) for c in (member.declared_by, *member.refined_by))
        )

    def _restricted_to(self, member: ResolvedChild) -> frozenset[str]:
        """The definitions a dispatch member's specialisation restricts
        ``definition`` to (§8.4), if any."""
        spec = member.specialisation
        if not spec:
            return frozenset()
        if spec not in self._restricted:
            values: set[str] = set()
            group = self.reader.group(spec)
            for child in group.children if group is not None else []:
                if child.id == self.profile.dispatch_dataset and child.enum:
                    values = {
                        v.value for v in child.enum.values if isinstance(v.value, str)
                    }
            if values <= {spec.split("/", 1)[0]}:
                values = set()
            self._restricted[spec] = frozenset(values)
        return self._restricted[spec]

    def _dispatch_fits(self, member: ResolvedChild, frame: _Frame, o: _Object) -> bool:
        if not o.dispatch:
            return False
        restricted = self._restricted_to(member)
        if restricted:
            return any(self._extends(o.dispatch, d) for d in restricted)
        return self._extends(o.dispatch, frame.app)

    def _choose(self, o: _Object, frame: _Frame) -> tuple[int | None, bool]:
        """The member an object is assigned to (§7), and whether by class fallback."""
        if o.kind is None and o.link == "external":
            # kind and class unknown: the first exact or template member (§9.8)
            for index, member in enumerate(frame.children):
                if isinstance(member.name, ExactName | TemplateName) and self._matches(
                    member.name, o.name
                ):
                    return index, False
            return None, False
        if o.kind is None:
            kinds = {"link"} if o.link else set()
        else:
            kinds = {o.kind, "link"} if o.link else {o.kind}
        candidates = []
        for index, member in enumerate(frame.children):
            if member.node not in kinds or isinstance(member.name, RefName):
                continue
            dispatch = member.node == "group" and self._is_dispatch(member, frame)
            if dispatch:
                if not self._dispatch_fits(member, frame, o):
                    continue
            elif not self._matches(member.name, o.name):
                continue
            if member.node == "group":
                if not o.nx_class or not self._is_subclass(o.nx_class, member.class_):
                    continue
            candidates.append(
                self._priority(frame.children, index, link=o.link is not None)
            )
        if candidates:
            return min(candidates)[-1], False
        if "group" in kinds:
            for index, member in enumerate(frame.children):
                if (
                    member.node == "group"
                    and isinstance(member.name, ExactName)
                    and member.name.exact == o.name
                    and not self._is_dispatch(member, frame)
                ):
                    return index, True
        return None, False

    def _choose_attribute(self, name: str, members: list) -> int | None:
        candidates = [
            self._priority(members, index)
            for index, member in enumerate(members)
            if self._matches(member.name, name)
        ]
        return min(candidates)[-1] if candidates else None

    @staticmethod
    def _totals(members: list, counts: dict[int, int]) -> dict[int, int]:
        """Objects per member, counting those of members that refine it (§9.1)
        and, for children, both forms of an item (§5.1; roles apart)."""

        def form(m: Any) -> str:
            return form_of(getattr(m, "node", "attribute"))

        totals = dict(counts)
        position = {(m.id, form(m)): i for i, m in enumerate(members)}
        for index, count in counts.items():
            member = members[index]
            seen = {index}
            while member.refines:
                parent = position.get((member.refines, form(member)))
                if parent is None or parent in seen:
                    break
                seen.add(parent)
                totals[parent] = totals.get(parent, 0) + count
                member = members[parent]
        shared: dict[str, list[int]] = {}
        for index, member in enumerate(members):
            if hasattr(member, "node") and not isinstance(member.name, RefName):
                shared.setdefault(member.id, []).append(index)
        combined = dict(totals)
        for indices in shared.values():
            if len(indices) > 1:
                total = sum(totals.get(i, 0) for i in indices)
                for i in indices:
                    combined[i] = total
        return combined

    # -------------------------------------------------------------- reading

    def _identity(self, obj: Any) -> tuple[str, int] | None:
        try:
            return obj.file.filename, h5py.h5o.get_info(obj.id).addr
        except Exception:
            return None

    def _children(self, group: h5py.Group, path: str) -> list[_Object]:
        try:
            names = sorted(group.keys(), key=_utf8)
        except Exception as exc:
            self._add("SKIPPED", path, None, f"cannot list members: {_error(exc)}")
            return []
        objects = []
        for name in names:
            child_path = _join(path, name)
            try:
                objects.append(self._object(group, name, child_path))
            except Exception as exc:
                self._add("SKIPPED", child_path, None, f"cannot read: {_error(exc)}")
        return objects

    def _object(self, group: h5py.Group, name: str, path: str) -> _Object:
        info = group.id.links.get_info(name.encode())
        link = None
        target = None
        if info.type == h5py.h5l.TYPE_SOFT:
            link = "soft"
            target = group.get(name, getlink=True).path
            if not target.startswith("/"):
                target = _join(path.rsplit("/", 1)[0] or "/", target)
        elif info.type == h5py.h5l.TYPE_EXTERNAL:
            link = "external"
        try:
            obj = group.get(name)
        except Exception:
            if link is None:
                raise
            obj = None
        kind = None
        if isinstance(obj, h5py.Group):
            kind = "group"
        elif isinstance(obj, h5py.Dataset):
            kind = "dataset"
        result = _Object(name, path, kind, link, obj, target=target)
        if obj is not None:
            result.identity = identity = self._identity(obj)
            if link == "soft":
                result.own = False
            elif link == "external":
                result.own = identity not in self._walked
            elif identity is not None and h5py.h5o.get_info(obj.id).rc > 1:
                own_path, has_target = self._own_path(obj, identity, path)
                if own_path != path:
                    result.own = False
                    result.link = "hard" if has_target else None
                    result.target = own_path
        if kind == "group":
            try:
                value = obj.attrs.get(self.profile.class_attribute)
            except Exception as exc:
                self._add("SKIPPED", path, None, f"class not readable: {_error(exc)}")
                value = None
            if value is not None:
                text = _text(value)
                if isinstance(text, list) and len(text) == 1:
                    text = text[0]
                result.nx_class = str(text)
        return result

    # ----------------------------------------------------------------- walk

    def _group(self, task: _Task) -> list[_Task]:
        frame, group, path = task.frame, task.group, task.path
        normal = not task.linked
        objects = self._children(group, path)
        by_name = {o.name: o for o in objects}
        if normal:
            for o in objects:
                if _lives_here(o) and o.nx_class in self.profile.entry_points:
                    self._dispatch(o, task.app)
        # assignment (§7.2, §7.3)
        member_of: dict[str, tuple[_Frame, int]] = {}
        counts: dict[int, int] = {}
        fallbacks: set[str] = set()
        for o in objects:
            index, fallback = self._choose(o, frame)
            if index is None:
                continue
            member_of[o.name] = (frame, index)
            counts[index] = counts.get(index, 0) + 1
            if fallback:
                fallbacks.add(o.name)
                member = frame.children[index]
                if normal and o.nx_class is None:
                    ref = self._ref(frame, member)
                    self._add("NO-CLASS", o.path, ref, "group without class")
                elif normal:
                    self._add(
                        "CLASS",
                        o.path,
                        self._ref(frame, member),
                        f"{o.nx_class} is not {member.class_}",
                    )
        # roles (§7.4)
        fills = self._roles(group, path, frame, by_name)
        filled = {o.name for _, o in fills}
        # objects of a subclass: what the frame leaves is matched to its own class
        if task.own is not None:
            for o in objects:
                if o.name not in member_of and o.name not in filled:
                    index, _ = self._choose(o, task.own)
                    if index is not None:
                        member_of[o.name] = (task.own, index)
        # occurrence (§9.1)
        totals = self._totals(frame.children, counts)
        counted: set[str] = set()
        for index, member in enumerate(frame.children):
            if isinstance(member.name, RefName) or member.id in counted:
                continue  # two forms of one item: once, with the first (§5.1)
            counted.add(member.id)
            self._occurrence(
                member, totals.get(index, 0), path, self._ref(frame, member)
            )
        # each object
        tasks: list[_Task] = []
        for o in objects:
            owner, index = member_of.get(o.name, (frame, None))
            member = owner.children[index] if index is not None else None
            ref = self._ref(owner, member) if member is not None else None
            if normal:
                self._object_checks(
                    o, member is not None, o.name in filled, frame, ref, fallbacks
                )
            if member is not None:
                self._assigned_checks(o, member, owner, task)
            tasks += self._child_tasks(o, member, owner, task, o.name in fallbacks)
        for member, o in fills:
            self._fill(o, member, frame, task)
        # attributes and constraints
        self._attributes(
            group,
            path,
            frame.attributes,
            frame.scope,
            frame.undeclared.attribute,
            task.entry,
            children=by_name,
            fills=fills,
            report=normal,
            own=task.own,
        )
        self._constraints(frame, totals, path)
        return tasks

    def _roles(
        self, group: Any, path: str, frame: _Frame, by_name: dict[str, _Object]
    ) -> list[tuple[ResolvedChild, _Object]]:
        fills: list[tuple[ResolvedChild, _Object]] = []
        for member in frame.children:
            if not isinstance(member.name, RefName):
                continue
            attribute = member.name.ref.lstrip("@")
            attribute_path = _attribute_path(path, attribute)
            ref = self._ref(frame, member)
            try:
                value = group.attrs.get(attribute)
            except Exception as exc:
                self._add("SKIPPED", attribute_path, ref, _error(exc))
                continue
            if value is None:
                continue
            for name in _names(value):
                if name == ".":
                    continue
                o = by_name.get(name)
                if o is None:
                    self._add("REF", attribute_path, ref, f"{name!r} names no child")
                    continue
                if o.kind is not None and o.kind != form_of(member.node):
                    self._add(
                        "REF",
                        attribute_path,
                        ref,
                        f"{name!r} is a {o.kind}, not a {form_of(member.node)}",
                    )
                    continue
                fills.append((member, o))
        return fills

    def _object_checks(
        self,
        o: _Object,
        assigned: bool,
        filled: bool,
        frame: _Frame,
        ref: str | None,
        fallbacks: set[str],
    ) -> None:
        """Checks of an object where it lives: name, class, undeclared."""
        if not self._valid_name(o.name):
            self._add("NAME", o.path, ref, "name outside the name rules")
        if _lives_here(o):
            if o.nx_class is None:
                if o.name not in fallbacks:  # else reported with its member
                    self._add("NO-CLASS", o.path, ref, "group without class")
            elif o.nx_class not in self.index.classes:
                self._add(
                    "UNKNOWN-CLASS", o.path, None, f"{o.nx_class} is not in the bundle"
                )
        if o.kind is None and o.link and not assigned:
            if o.link == "external":
                self._add("SKIPPED", o.path, None, "external file not readable")
            else:
                self._add("LINK", o.path, None, "dangling link", condition="dangling")
        if assigned or filled:
            return
        kind = o.kind if o.kind in ("group", "dataset") else "dataset"
        policy = getattr(frame.undeclared, kind)
        if policy != "ignore":
            self._add(
                "UNDECLARED",
                o.path,
                None,
                f"undeclared {o.kind or 'link'}",
                exception="undeclared_error" if policy == "error" else None,
            )

    def _assigned_checks(
        self, o: _Object, member: ResolvedChild, frame: _Frame, task: _Task
    ) -> None:
        """The checks of the member an object is assigned to (§9)."""
        ref = self._ref(frame, member)
        if member.deprecated:
            self._add("DEPRECATED", o.path, ref, member.deprecated)
        chain = (*task.chain, (self._labels(frame.children, member), o.path))
        if o.identity is not None and o.dispatch_member is None:
            self._record(o.identity, chain)
            external = o.identity[0] != self._root.filename
            if external and not task.linked and member.node != "link":
                self._external.setdefault(o.identity, o.path)
        if o.kind is None:
            if o.link == "external":
                self._add("SKIPPED", o.path, ref, "external file not readable")
            elif o.link:
                self._add("LINK", o.path, ref, "dangling link", condition="dangling")
            return
        if member.node == "link":
            if member.target and o.identity is not None:
                self._link_check(o, member, ref, chain, frame, task)
            return
        if o.kind == "dataset" and member.node == "dataset":
            self._dataset(o, member, ref, frame, task.entry)

    def _link_check(
        self,
        o: _Object,
        member: ResolvedChild,
        ref: str,
        chain: tuple[_Step, ...],
        frame: _Frame,
        task: _Task,
    ) -> None:
        target = member.target or ""
        if target.startswith("/"):
            base, target = 1, target[1:]
        elif frame.app is not None and "/" in frame.scope:
            base = task.base
        else:
            base = len(task.chain)
        check = _LinkCheck(
            path=o.path,
            member=ref,
            identity=o.identity,
            chain=chain,
            base=base,
            steps=[label_step(s)[0] for s in target.split("/")],
        )
        own = o.target if o.target and o.identity[0] == self._root.filename else None
        if own is not None and _components(own) < _components(o.path):
            check.earlier = own  # walked already: re-derived at the end
        elif o.identity in self._external:
            check.earlier = self._external[o.identity]  # of another file, ditto
        else:
            self._assigned.setdefault(o.identity, [])
        self._links.append(check)

    def _record(self, identity: tuple[str, int], chain: tuple[_Step, ...]) -> None:
        """Remember an assignment only for objects a link check waits for."""
        if identity in self._assigned:
            self._assigned[identity].append(chain)

    def _fill(
        self, o: _Object, member: ResolvedChild, frame: _Frame, task: _Task
    ) -> None:
        """A child named by a role: the role's checks apply as well (§7.4)."""
        if o.kind is None:
            return  # a dangling or unopened link fills the role without checks
        ref = self._ref(frame, member)
        if member.deprecated:
            self._add("DEPRECATED", o.path, ref, member.deprecated)
        if o.kind == "dataset" and member.node == "dataset":
            self._dataset(o, member, ref, frame, task.entry)

    def _child_tasks(
        self,
        o: _Object,
        member: ResolvedChild | None,
        frame: _Frame,
        task: _Task,
        fallback: bool,
    ) -> list[_Task]:
        if o.kind != "group" or o.obj is None or frame.unknown:
            return []
        if member is not None and member.node == "link":
            return []
        chain = (*task.chain, (self._labels(frame.children, member), o.path))
        if task.linked or not o.own or o.link in ("soft", "hard"):
            # reached through a link: only the specialisation is applied (§9.8)
            if member is None or fallback or not member.specialisation:
                return []
            spec = self._make_frame(member.specialisation)
            if spec is None:
                return []
            return [
                _Task(
                    o.obj,
                    o.path,
                    spec,
                    task.entry,
                    chain,
                    task.base,
                    linked=True,
                    app=task.app,
                )
            ]
        if o.identity is not None:
            if o.identity in self._walked:
                return []
            self._walked.add(o.identity)
        if o.dispatch_member is not None:
            dispatch = o.dispatch_member
            child = self._member_frame(dispatch, o)
            app_root = self._class_frame(o.dispatch)
            labels = self._labels(app_root.children if app_root else [], dispatch)
            chain = (*task.chain, (labels, o.path))
            if o.identity is not None:
                self._record(o.identity, chain)
            entry = task.entry
            tasks = []
            if entry is None or entry.path == "/":
                entry = _Entry(o.path, stopped=self._stopped(o))
                tasks.append(_Task(post=lambda e=entry: self._symbols(e)))
            return [
                _Task(
                    o.obj,
                    o.path,
                    child,
                    entry,
                    chain,
                    len(task.chain),
                    app=o.dispatch,
                    own=self._leftovers(child, o),
                ),
                *tasks,
            ]
        if fallback or member is None:
            child = self._class_frame(o.nx_class) or _empty_frame(
                o.nx_class or "", frame.undeclared
            )
            own = None
        else:
            child = self._member_frame(member, o)
            own = self._leftovers(child, o)
        return [
            _Task(
                o.obj,
                o.path,
                child,
                task.entry,
                chain,
                task.base,
                app=task.app,
                own=own,
            )
        ]

    def _stopped(self, o: _Object) -> bool:
        try:
            value = o.obj.attrs.get(self.profile.stopped_attribute)
        except Exception:
            return False
        return value is not None and _text(value) == self.profile.stopped_value

    # ------------------------------------------------------------- dispatch

    def _dispatch(self, o: _Object, inside: str | None) -> None:
        """The application definition a group follows (§8.2–§8.4)."""
        name = self.profile.dispatch_dataset
        path = _join(o.path, name)
        try:
            dataset = o.obj.get(name)
        except Exception as exc:
            self._add("SKIPPED", path, None, f"cannot read: {_error(exc)}")
            return
        if dataset is None:
            o.dispatch = inside  # counts as dispatched to the enclosing definition
            if inside is not None and not self._quiet:
                self._dispatched.append((inside, o.nx_class))
            return
        member = self._class_member_ref(o.nx_class, name)
        value = None
        try:
            if (
                isinstance(dataset, h5py.Dataset)
                and dataset.size == 1
                and _storage(dataset.dtype) == "string"
            ):
                value = _text(dataset[()])
                if isinstance(value, list):
                    value = value[0]
        except Exception as exc:
            self._add("SKIPPED", path, member, f"cannot read: {_error(exc)}")
            return
        if not isinstance(value, str):
            self._add("TYPE", path, member, "not a dataset with one text value")
            return
        if not self._is_app(value):
            self._add(
                "UNKNOWN-DEFINITION",
                path,
                None,
                f"{value!r} is not an application definition of the bundle",
            )
            return
        selected = self._dispatch_member(value, o)
        if selected is None:
            return
        o.dispatch, o.dispatch_member = value, selected
        if not self._quiet:
            self._dispatched.append((value, o.nx_class))

    def _class_member_ref(self, nx_class: str | None, label: str) -> str | None:
        frame = self._class_frame(nx_class)
        if frame is None:
            return None
        for member in frame.children:
            if member.id == label and member.node == "dataset":
                return self._ref(frame, member)
        return None

    def _dispatch_member(self, app: str, o: _Object) -> ResolvedChild | None:
        """§8.2: among the dispatch members of the definition whose class is the
        group's class or a superclass, the one chosen by §7.3; else the first."""
        frame = self._class_frame(app)
        if frame is None:
            return None
        members = frame.children
        indices = [i for i, m in enumerate(members) if self._is_dispatch(m, frame)]
        fitting = [
            i for i in indices if self._is_subclass(o.nx_class, members[i].class_)
        ]
        if fitting:
            best = min(
                fitting,
                key=lambda i: (
                    not self._matches(members[i].name, o.name),
                    self._priority(members, i),
                ),
            )
            return members[best]
        return members[indices[0]] if indices else None

    def _root_level(self) -> None:
        """The root against the root-level members of each dispatched-to
        definition (§8.6): path ``/``, member ``A/<label>``."""
        for app in sorted({app for app, _ in self._dispatched}):
            frame = self._class_frame(app)
            if frame is None:
                continue
            lineage = self._lineage(app)
            members = frame.children
            counts: dict[int, int] = {}
            for dispatched, nx_class in self._dispatched:
                if not self._extends(dispatched, app):
                    continue
                probe = _Object("", "", "group", None, nx_class=nx_class)
                selected = self._dispatch_member(app, probe)
                if selected is not None:
                    index = members.index(selected)
                    counts[index] = counts.get(index, 0) + 1
            totals = self._totals(members, counts)
            for index, member in enumerate(members):
                if self._is_dispatch(member, frame) and self._written_by(
                    member, lineage
                ):
                    self._occurrence(
                        member, totals.get(index, 0), "/", self._ref(frame, member)
                    )
            written = [a for a in frame.attributes if self._written_by(a, lineage)]
            self._attributes(
                self._root, "/", written, app, "ignore", None, report=False
            )

    def _lineage(self, app: str) -> set[str]:
        result = set()
        while app and app not in result:
            result.add(app)
            entry = self.index.classes.get(app)
            app = entry.extends if entry is not None else None
        return result

    @staticmethod
    def _written_by(member: Any, classes: set[str]) -> bool:
        return any(c in classes for c in (member.declared_by, *member.refined_by))

    def _no_definition(self) -> None:
        """§8.8: the expected application definition, or none at all."""
        if self.expect:
            frame = (
                self._class_frame(self.expect) if self._is_app(self.expect) else None
            )
            required = 1
            if frame is not None:
                required = max(
                    1,
                    sum(
                        m.occurs.min
                        for m in frame.children
                        if self._is_dispatch(m, frame)
                    ),
                )
            found = sum(
                1 for app, _ in self._dispatched if self._extends(app, self.expect)
            )
            if frame is None or found < required:
                self._add(
                    "NO-DEFINITION",
                    "/",
                    self.expect,
                    f"{found} groups follow {self.expect}, {required} required",
                    exception="expect",
                )
        elif not self._dispatched:
            self._add(
                "NO-DEFINITION", "/", None, "no group names an application definition"
            )

    # -------------------------------------------------------------- checks

    def _occurrence(self, member: Any, count: int, path: str, ref: str) -> None:
        occurs = member.occurs
        if count < occurs.min:
            self._add("MISSING", path, ref, f"{count} of at least {occurs.min}")
        elif count == 0 and member.recommended:
            self._add("RECOMMENDED", path, ref)
        if occurs.max != "unbounded" and count > occurs.max:
            self._add("TOO-MANY", path, ref, f"{count} > {occurs.max}")

    def _constraints(self, frame: _Frame, totals: dict[int, int], path: str) -> None:
        """§9.6: constraints count present members."""
        present: set[str] = set()
        for index, member in enumerate(frame.children):
            if totals.get(index, 0):
                present.add(member.id)
        for constraint in frame.require:
            kind, labels = constraint_kind(constraint)
            count = sum(1 for label in labels if label_step(label)[0] in present)
            ok, missing = {
                "at_least_one_of": (count >= 1, True),
                "exactly_one_of": (count == 1, count == 0),
                "at_most_one_of": (count <= 1, False),
                "all_or_none": (count in (0, len(labels)), True),
            }[kind]
            if not ok:
                self._add(
                    "CONSTRAINT",
                    path,
                    f"{frame.scope}:{kind}[{','.join(labels)}]",
                    f"{count} of {', '.join(labels)} present",
                    condition="missing" if missing else None,
                )

    def _dataset(
        self,
        o: _Object,
        member: ResolvedChild,
        ref: str,
        frame: _Frame,
        entry: _Entry | None,
    ) -> None:
        dataset = o.obj
        try:
            dtype, shape, maxshape = dataset.dtype, dataset.shape, dataset.maxshape
        except Exception as exc:
            self._add("SKIPPED", o.path, ref, f"cannot read: {_error(exc)}")
            return
        storage = _storage(dtype)
        growable = maxshape is not None and any(
            m is None or m > s for m, s in zip(maxshape, shape, strict=False)
        )
        if member.type:
            self._type(member.type, storage, shape, o.path, ref)
        self._shape(member, shape, growable, o.path, ref, entry)
        if self._needs_values(member, storage):
            size = int(np.prod(shape)) if shape else 1
            if size == 1:
                try:
                    value = _text(dataset[()])
                except Exception as exc:
                    self._add("SKIPPED", o.path, ref, f"cannot read: {_error(exc)}")
                else:
                    self._values(member, storage, value, o.path, ref)
            elif size > 1 and ref not in self._skipped_members:
                self._skipped_members.add(ref)
                self._add(
                    "SKIPPED", o.path, ref, "values of arrays not checked (tier F)"
                )
        if member.units is not None:
            self._units(member, dataset, o.path, ref)
        self._attributes(
            dataset,
            o.path,
            member.attributes,
            ref,
            frame.undeclared.attribute,
            entry,
        )

    def _needs_values(self, member: Any, storage: str) -> bool:
        if member.enum is not None:
            return True
        type_def = self.index.types.get(member.type or "")
        if type_def is None:
            return False
        if type_def.min_value is not None:
            return True
        if "xs:boolean" in type_def.builtins:
            return storage in ("int8", "uint8")
        return "xs:dateTime" in type_def.builtins

    def _type(
        self, type_name: str, storage: str, shape: tuple, path: str, ref: str
    ) -> None:
        accepted = self.profile.storage.get(type_name)
        if accepted is None:
            self._add("SKIPPED", path, ref, f"no storage types for {type_name}")
            return
        if storage not in accepted:
            self._add("TYPE", path, ref, f"{storage} is not {type_name}")
            return
        type_def = self.index.types.get(type_name)
        if (
            type_def is not None
            and type_def.variety == "list"
            and type_def.length
            and storage.startswith("float")
            and (not shape or shape[-1] != type_def.length)
        ):
            self._add("TYPE", path, ref, f"last dimension is not {type_def.length}")

    def _values(
        self, member: Any, storage: str, value: Any, path: str, ref: str
    ) -> None:
        """Value checks of the type and the enumeration (§4.5, §9.2)."""
        items = value if isinstance(value, list) else [value]
        type_def = self.index.types.get(member.type or "")
        for item in items:
            if type_def is None:
                break
            number = isinstance(item, (int, float)) and not isinstance(item, bool)
            if type_def.min_value is not None and number and item < type_def.min_value:
                self._add("TYPE", path, ref, f"{item} < {type_def.min_value:g}")
            if (
                "xs:boolean" in type_def.builtins
                and storage in ("int8", "uint8")
                and item not in (0, 1)
            ):
                self._add("TYPE", path, ref, f"{item!r} is not 0 or 1")
            if "xs:dateTime" in type_def.builtins and not _is_date_time(item):
                self._add("TYPE", path, ref, f"{item!r} is not a date and time")
        if member.enum is None:
            return

        def stored(x: Any) -> Any:
            # numbers compare after conversion to the stored type (float32 0.1)
            return _key(_as_stored(x, storage))

        scalars = {
            stored(v.value): v
            for v in member.enum.values
            if not isinstance(v.value, list)
        }
        arrays = {
            tuple(stored(x) for x in v.value): v
            for v in member.enum.values
            if isinstance(v.value, list)
        }
        code = "ENUM-OPEN" if member.enum.open else "ENUM"
        values = ", ".join(str(v.value) for v in member.enum.values)
        if isinstance(value, list) and len(value) != 1:
            whole = arrays.get(tuple(_key(x) for x in value))
            if whole is not None:
                if whole.deprecated:
                    self._add("DEPRECATED", path, ref, f"{value!r}: {whole.deprecated}")
                return
            if not scalars:
                self._add(code, path, ref, f"{value!r} not in [{values}]")
                return
        for item in items:
            found = scalars.get(_key(item))
            if found is None:
                self._add(code, path, ref, f"{item!r} not in [{values}]")
            elif found.deprecated:
                self._add("DEPRECATED", path, ref, f"{item!r}: {found.deprecated}")

    def _shape(
        self,
        member: Any,
        actual: tuple,
        growable: bool,
        path: str,
        ref: str,
        entry: _Entry | None,
    ) -> None:
        """§9.3: rank, dimensions and symbol bindings of a binding shape."""
        shape = member.shape
        if shape is None or not shape.binding:
            return
        scope = shape.symbols
        rank = len(actual)
        use = _Use(rank, path, growable)
        if isinstance(shape.rank, str) and entry is not None:
            key = (scope.get(shape.rank, ""), shape.rank)
            entry.values.setdefault(key, []).append(use)
        elif isinstance(shape.rank, DimExpr) and entry is not None:
            entry.expressions.append((shape.rank.expr, scope, use))
        problems = []
        dims = shape.dims
        if dims is None:
            if isinstance(shape.rank, int) and rank != shape.rank:
                problems.append(f"rank {rank} where {shape.rank} is declared")
        else:
            required = sum(1 for d in dims if not isinstance(d, OptionalDim))
            if not required <= rank <= len(dims):
                if (rank == 0 and dims == [1]) or (actual == (1,) and dims == []):
                    self._add(
                        "SHAPE",
                        path,
                        ref,
                        f"shape {actual} where {dims} is declared",
                        exception="scalar_against_length_1",
                    )
                    return
                expected = (
                    str(required)
                    if required == len(dims)
                    else f"{required} to {len(dims)}"
                )
                problems.append(f"rank {rank} where {expected} is declared")
            else:
                for index, dim in enumerate(dims[:rank]):
                    if isinstance(dim, OptionalDim):
                        dim = dim.value
                    length = actual[index]
                    if isinstance(dim, int) and length != dim:
                        problems.append(f"dimension {index + 1} is {length}, not {dim}")
                    elif isinstance(dim, str) and entry is not None:
                        key = (scope.get(dim, ""), dim)
                        entry.values.setdefault(key, []).append(
                            _Use(length, path, growable)
                        )
                    elif isinstance(dim, DimExpr) and entry is not None:
                        entry.expressions.append(
                            (dim.expr, scope, _Use(length, path, growable))
                        )
        if problems:
            self._add(
                "SHAPE",
                path,
                ref,
                "; ".join(problems),
                condition="growing" if growable else None,
            )

    def _symbols(self, entry: _Entry) -> None:
        """One SHAPE per symbol and entry whose binding uses disagree (§9.3)."""
        reported: set[tuple[str, str]] = set()
        for key, uses in sorted(entry.values.items()):
            if len({u.value for u in uses}) > 1:
                reported.add(key)
                self._symbol_conflict(entry, key, uses)
        for expression, scope, use in entry.expressions:
            names = _IDENTIFIER.findall(expression)
            keys = [(scope.get(n, ""), n) for n in names]
            if not keys or any(k in reported or k not in entry.values for k in keys):
                continue
            values = {
                n: entry.values[k][0].value for n, k in zip(names, keys, strict=True)
            }
            try:
                expected = _evaluate(expression, values)
            except (ValueError, ZeroDivisionError):
                continue
            if expected != use.value:
                reported.add(keys[0])
                uses = [*entry.values[keys[0]], use]
                self._symbol_conflict(
                    entry, keys[0], uses, f"{expression} = {expected}"
                )

    def _symbol_conflict(
        self,
        entry: _Entry,
        key: tuple[str, str],
        uses: list[_Use],
        detail: str | None = None,
    ) -> None:
        scope, symbol = key
        message = ", ".join(f"{u.path}: {u.value}" for u in uses)
        if detail:
            message += f" ({detail})"
        self._add(
            "SHAPE",
            entry.path,
            f"{scope}#{symbol}",
            message,
            exception="stopped_entry" if entry.stopped else None,
            condition="growing" if any(u.growable for u in uses) else None,
        )

    def _units(self, member: Any, dataset: Any, path: str, ref: str) -> None:
        """§14: the units attribute and its dimensions."""
        name = self.profile.units_attribute
        try:
            value = dataset.attrs.get(name)
        except Exception as exc:
            self._add("SKIPPED", _attribute_path(path, name), ref, _error(exc))
            return
        if value is None:
            self._add("UNITS", path, ref, "no units", condition="absent")
            return
        text = _text(value)
        if isinstance(text, list) and len(text) == 1:
            text = text[0]
        if not isinstance(text, str):
            self._add("UNITS", path, ref, f"units {text!r} are not text")
            return
        symbols = self.index.unit_symbols
        if isinstance(member.units, UnitsCategory):
            category = member.units.category
            known = self.index.units.get(category)
            if known is None:
                return
            if text == "" and known.empty:
                return
            if known.dimensions is None:
                return  # any unit string (NX_ANY)
            try:
                found = dimensions(text, symbols)
            except UnitsError:
                self._add("UNITS", path, ref, f"units {text!r} not understood")
                return
            if found not in known.dimensions:
                self._add("UNITS", path, ref, f"{text!r} is not {category}")
            return
        try:
            same = normalise(text, symbols) == normalise(member.units.fixed, symbols)
        except UnitsError:
            same = False
        if not same:
            self._add("UNITS", path, ref, f"{text!r} is not {member.units.fixed!r}")

    def _attributes(
        self,
        obj: Any,
        path: str,
        members: list[ResolvedAttribute],
        prefix: str,
        policy: str,
        entry: _Entry | None,
        children: dict[str, _Object] | None = None,
        fills: list | None = None,
        report: bool = True,
        own: _Frame | None = None,
    ) -> None:
        """Attributes against members; with ``own``, what they leave undeclared
        is matched against the group's own class, member checks only (§8.7)."""
        try:
            names = sorted(obj.attrs.keys(), key=_utf8)
        except Exception as exc:
            self._add("SKIPPED", path, None, f"attributes not readable: {_error(exc)}")
            return
        counts: dict[int, int] = {}
        assigned: list[tuple[str, int]] = []
        for name in names:
            attribute_path = _attribute_path(path, name)
            index = self._choose_attribute(name, members)
            if index is None and own is not None:
                extra = self._choose_attribute(name, own.attributes)
                if extra is not None:
                    member = own.attributes[extra]
                    self._attribute(
                        obj,
                        name,
                        member,
                        path,
                        f"{own.scope}@{member.id}",
                        entry,
                        children,
                        fills,
                    )
                    continue
            ref = f"{prefix}@{members[index].id}" if index is not None else None
            if report and not self._valid_name(name):
                self._add("NAME", attribute_path, ref, "name outside the name rules")
            if index is None:
                if (
                    report
                    and name not in self._profile_attributes
                    and policy != "ignore"
                ):
                    self._add(
                        "UNDECLARED",
                        attribute_path,
                        None,
                        "undeclared attribute",
                        exception="undeclared_error" if policy == "error" else None,
                    )
                continue
            counts[index] = counts.get(index, 0) + 1
            assigned.append((name, index))
        totals = self._totals(members, counts)
        for index, member in enumerate(members):
            self._occurrence(
                member, totals.get(index, 0), path, f"{prefix}@{member.id}"
            )
        for name, index in assigned:
            member = members[index]
            ref = f"{prefix}@{member.id}"
            try:
                self._attribute(obj, name, member, path, ref, entry, children, fills)
            except Exception as exc:
                self._add(
                    "SKIPPED",
                    _attribute_path(path, name),
                    ref,
                    f"cannot read: {_error(exc)}",
                )

    def _attribute(
        self,
        obj: Any,
        name: str,
        member: ResolvedAttribute,
        owner: str,
        ref: str,
        entry: _Entry | None,
        children: dict[str, _Object] | None,
        fills: list | None,
    ) -> None:
        path = _attribute_path(owner, name)
        if member.deprecated:
            self._add("DEPRECATED", path, ref, member.deprecated)
        raw = obj.attrs[name]
        array = np.asarray(raw)
        text = isinstance(raw, (str, bytes))
        storage = "string" if text else _storage(array.dtype)
        shape = () if text else array.shape
        if member.type:
            self._type(member.type, storage, shape, path, ref)
        self._shape(member, shape, False, path, ref, entry)
        value = _text(raw)
        self._values(member, storage, value, path, ref)
        items = value if isinstance(value, list) else [value]
        if member.names_child and children is not None:
            for item in items:
                if item == ".":
                    continue
                child = children.get(str(item))
                if child is None:
                    self._add("REF", path, ref, f"{item!r} names no child")
                elif child.kind is not None and child.kind != member.names_child:
                    self._add(
                        "REF",
                        path,
                        ref,
                        f"{item!r} is a {child.kind}, not a {member.names_child}",
                    )
        if member.length is not None:
            self._length(member, len(items), path, owner, ref, entry, fills)
        if isinstance(member.rank, int) and len(shape) != member.rank:
            self._add(
                "CONSTRAINT",
                owner,
                f"{ref}:rank",
                f"rank {len(shape)}, not {member.rank}",
            )

    def _length(
        self,
        member: ResolvedAttribute,
        count: int,
        path: str,
        owner: str,
        ref: str,
        entry: _Entry | None,
        fills: list | None,
    ) -> None:
        """§9.6: the number of elements of an array-valued attribute."""
        length = member.length
        expected = None
        if isinstance(length, int):
            expected = length
        elif isinstance(length, RankOf):
            for role, o in fills or []:
                if role.id == length.rank_of and o.kind == "dataset":
                    try:
                        expected = len(o.obj.shape)
                    except Exception:
                        expected = None
                    break
        elif isinstance(length, str) and entry is not None:
            key = (ref.split("/", 1)[0].split("@", 1)[0], length)
            entry.values.setdefault(key, []).append(_Use(count, path, False))
            return
        if expected is not None and count != expected:
            self._add(
                "CONSTRAINT",
                owner,
                f"{ref}:length",
                f"{count} elements, not {expected}",
                condition="missing" if count < expected else None,
            )

    # ----------------------------------------------------------------- links

    def _check_links(self) -> None:
        """§9.8: the object a link points to is assigned to the target member."""
        derived: dict[str, list[tuple[_Step, ...]]] = {}
        for check in self._links:
            if check.earlier is not None:
                if check.earlier not in derived:
                    derived[check.earlier] = self._rederive(check.earlier)
                chains = derived[check.earlier]
            else:
                chains = self._assigned.get(check.identity, [])
            if not any(_fits(c, check) for c in chains):
                where = sorted(
                    {"/".join(sorted(c[-1][0])) or "undeclared" for c in chains}
                )
                self._add(
                    "LINK",
                    check.path,
                    check.member,
                    f"the object is assigned to {', '.join(where) or 'nothing'}, "
                    f"not {'/'.join(check.steps)}",
                )

    def _rederive(self, path: str) -> list[tuple[_Step, ...]]:
        """The assignment of an object already walked, found again by matching
        the groups on its path (nothing is reported)."""
        self._quiet = True
        try:
            task = _Task(
                self._root,
                "/",
                self._class_frame(self.profile.root_class) or _empty_frame(""),
                None,
                ((frozenset(), "/"),),
            )
            names = path.strip("/").split("/")
            for position, name in enumerate(names):
                o = self._object(task.group, name, _join(task.path, name))
                if _lives_here(o) and o.nx_class in self.profile.entry_points:
                    self._dispatch(o, task.app)
                index, fallback = self._choose(o, task.frame)
                if index is None and task.own is not None:
                    index, _ = self._choose(o, task.own)
                    frame = task.own
                else:
                    frame = task.frame
                member = frame.children[index] if index is not None else None
                if position == len(names) - 1:
                    if member is None:
                        return []
                    return [(*task.chain, (self._labels(frame.children, member), path))]
                walked = self._walked
                self._walked = set()
                try:
                    tasks = self._child_tasks(o, member, frame, task, fallback)
                finally:
                    self._walked = walked
                if not tasks:
                    return []
                task = tasks[0]
            return []
        except Exception:
            return []
        finally:
            self._quiet = False


# ------------------------------------------------------------------ helpers


def _lives_here(o: _Object) -> bool:
    """A group walked at this path: its own path, or reached by an external link."""
    return o.kind == "group" and o.own and o.link in (None, "external")


def _empty_frame(nx_class: str, policy: UndeclaredPerKind | None = None) -> _Frame:
    """The frame of a group without class (its children undeclared, with the
    parent's policy) or of an unknown class (not walked further) (§7.2, §7.3)."""
    return _Frame(
        nx_class,
        nx_class,
        None,
        [],
        [],
        [],
        policy or UndeclaredPerKind(),
        unknown=bool(nx_class),
    )


def _fits(chain: tuple[_Step, ...], check: _LinkCheck) -> bool:
    """Whether an assignment of the target is the member the link names (§9.8)."""
    base, steps, link = check.base, check.steps, check.chain
    if len(chain) != base + len(steps) or len(link) < base:
        return False
    if any(chain[i][1] != link[i][1] for i in range(base)):
        return False
    if any(step not in chain[base + i][0] for i, step in enumerate(steps)):
        return False
    common = 0
    while (
        common < len(steps)
        and base + common < len(link)
        and steps[common] in link[base + common][0]
    ):
        common += 1
    return all(chain[base + i][1] == link[base + i][1] for i in range(common))


def _components(path: str) -> tuple[bytes, ...]:
    """A path as the order in which the walk visits it (byte order per level)."""
    return tuple(_utf8(p) for p in path.strip("/").split("/") if p)


def _join(path: str, name: str) -> str:
    return f"/{name}" if path == "/" else f"{path}/{name}"


def _attribute_path(path: str, name: str) -> str:
    return f"{path}@{name}"


def _utf8(name: str) -> bytes:
    return name.encode("utf-8", "surrogateescape")


def _error(exc: BaseException) -> str:
    text = str(exc).splitlines()[0] if str(exc) else ""
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _text(value: Any) -> Any:
    """A value read from the file as Python values; text without trailing NULs."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").rstrip("\x00")
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, np.ndarray):
        if value.shape == ():
            return _text(value[()])
        return [_text(v) for v in value.ravel().tolist()]
    if isinstance(value, np.generic):
        return _text(value.item())
    return value


def _names(value: Any) -> list[str]:
    value = _text(value)
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _key(value: Any) -> Any:
    """Enumeration values compare as text, numbers as numbers (``1`` = ``1.0``)."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return ("number", float(value))
    return ("text", str(value))


def _as_stored(value: Any, storage: str) -> Any:
    """A number as the storage type would hold it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if not storage.startswith(("int", "uint", "float")):
        return value
    try:
        return np.array(value, dtype=storage).item()
    except (TypeError, ValueError, OverflowError):
        return value


def _storage(dtype: np.dtype) -> str:
    """The storage type of an HDF5 datatype, by the names of the profile (§13.1);
    an array of strings is text (§12.2)."""
    if h5py.check_string_dtype(dtype) is not None or dtype.kind in "SU":
        return "string"
    if dtype.kind == "b":
        return "bool"
    if dtype.kind in "iufc":
        prefix = {"i": "int", "u": "uint", "f": "float", "c": "complex"}[dtype.kind]
        return f"{prefix}{dtype.itemsize * 8}"
    if dtype.kind == "V" and dtype.names and len(dtype.names) == 2:
        fields = [dtype.fields[n][0] for n in dtype.names]
        if all(f.kind == "f" for f in fields) and fields[0] == fields[1]:
            return "compound-2-floats"
    return "other"


def _is_date_time(value: Any) -> bool:
    """§13.2: ``xs:dateTime``, a space allowed instead of ``T``, time zone optional,
    an offset also without colon."""
    match = _DATE_TIME.fullmatch(str(value))
    if match is None:
        return False
    month, day, hour, minute, second = (int(match.group(i)) for i in range(2, 7))
    return (
        1 <= month <= 12
        and 1 <= day <= 31
        and (hour < 24 or (hour == 24 and minute == second == 0))
        and minute < 60
        and second < 60
    )


def _evaluate(expression: str, values: dict[str, int]) -> int:
    """A dimension expression with ``+``, ``-``, ``*``, integers and symbols."""

    def visit(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
        raise ValueError(f"not a dimension expression: {expression!r}")

    return visit(ast.parse(expression, mode="eval"))
