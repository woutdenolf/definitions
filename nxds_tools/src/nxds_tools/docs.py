"""reStructuredText documentation of every class, rendered from the bundle."""

from pathlib import Path

from .bundle import BundleReader
from .model import AnyName
from .model import ExactName
from .model import RefName
from .model import ResolvedAttribute
from .model import ResolvedChild
from .model import ResolvedClass
from .model import TemplateName
from .model import UnitsCategory
from .model import constraint_kind

_STATUS_TITLES = {
    "base": "Base classes",
    "application": "Application definitions",
    "contributed": "Contributed definitions",
    "dormant": "Dormant definitions",
    "local": "Local definitions",
}


def write_docs(bundle: BundleReader, out: Path, names: list[str] | None = None) -> None:
    """One ``<NXclass>.rst`` per class, an ``index.rst`` and a Sphinx ``conf.py``.

    With ``names``, only the pages of those classes.
    """
    out.mkdir(parents=True, exist_ok=True)
    for name in bundle.index.classes:
        if names is None or name in names:
            (out / f"{name}.rst").write_text(render_class(bundle, bundle.group(name)))
    if names is not None:
        return
    (out / "index.rst").write_text(_index(bundle))
    (out / "conf.py").write_text(
        'project = "NeXus classes (NXDS)"\n'
        'html_theme = "alabaster"\n'
        "extensions = ['sphinx.ext.todo']\n"
        "exclude_patterns = []\n"
        "suppress_warnings = ['ref.ref', 'ref.any', 'toc.not_included']\n"
    )


def render_class(bundle: BundleReader, resolved: ResolvedClass) -> str:
    """The page of one class: its documentation, symbols and members."""
    name = resolved.class_
    lines = [f".. _{name}:", "", name, "=" * len(name), ""]
    facts = [f"**Category:** {resolved.category}", f"**Status:** {resolved.status}"]
    if resolved.extends:
        facts.append(f"**Extends:** :ref:`{resolved.extends}`")
    if resolved.describes:
        facts.append(f"**Describes:** :ref:`{resolved.describes}`")
    facts.append(f"**Source:** ``{resolved.source}``")
    if resolved.lossy:
        facts.append(f"**Lossy in NXDL:** {', '.join(resolved.lossy)}")
    lines += [" · ".join(facts), ""]
    if resolved.deprecated:
        lines += [f".. warning:: Deprecated: {resolved.deprecated}", ""]
    doc = bundle.doc(name)
    if doc:
        lines += [doc, ""]
    if resolved.symbols:
        lines += ["Symbols", "-------", ""]
        for symbol in resolved.symbols:
            text = bundle.doc(f"{name}#{symbol}")
            lines += [f"- ``{symbol}``: {_one_line(text) if text else ''}"]
        lines.append("")
    lines += ["Members", "-------", "", _legend(), ""]
    lines += _members(
        bundle, name, resolved.attributes, resolved.children, resolved.require, 0
    )
    return "\n".join(lines) + "\n"


def _legend() -> str:
    return (
        "*required* means at least one object, *recommended* that its absence is "
        "reported, *optional* neither. Values marked *provisional* depend on an open "
        "decision of the NIAC."
    )


def _members(
    bundle: BundleReader,
    owner: str,
    attributes: list,
    children: list,
    require: list,
    depth: int,
) -> list[str]:
    indent = "  " * depth
    lines = []
    for attribute in attributes:
        lines += _member_lines(bundle, owner, attribute, depth)
    for child in children:
        lines += _member_lines(bundle, owner, child, depth)
    for constraint in require:
        kind, members = constraint_kind(constraint)
        lines += [
            f"{indent}- *constraint:* {kind.replace('_', ' ')}: {', '.join(f'``{m}``' for m in members)}",
            "",
        ]
    return lines


def _requirement(member) -> str:
    occurs = member.occurs
    if occurs.max == 0:
        return "forbidden"
    if occurs.min >= 1:
        text = "required"
    elif member.recommended:
        text = "recommended"
    else:
        text = "optional"
    if not (occurs.min in (0, 1) and occurs.max == 1):
        text += f" [{occurs.min}..{'∞' if occurs.max == 'unbounded' else occurs.max}]"
    return text


def _name(member) -> str:
    name = member.name
    if isinstance(name, ExactName):
        return f"**{name.exact}**"
    if isinstance(name, TemplateName):
        return f"**{name.template}** (name template)"
    if isinstance(name, AnyName):
        return f"**{member.id}** (any name)"
    if isinstance(name, RefName):
        return f"**{member.id}** (the dataset named by ``{name.ref}``)"
    return f"**{member.id}**"


def _member_lines(bundle: BundleReader, owner: str, member, depth: int) -> list[str]:
    indent = "  " * depth
    body = indent + "  "
    if isinstance(member, ResolvedAttribute):
        head = (
            f"@{_name(member)[2:-2]}"
            if isinstance(member.name, ExactName)
            else f"@{_name(member)}"
        )
        if isinstance(member.name, ExactName):
            head = f"**@{member.name.exact}**"
        kind = "attribute"
    else:
        head = _name(member)
        kind = member.node
    parts = [kind]
    if isinstance(member, ResolvedChild) and member.class_:
        parts.append(f":ref:`{member.class_}`")
    if member.type:
        parts.append(f"``{member.type}``")
    if member.units is not None:
        parts.append(
            f"units ``{member.units.category}``"
            if isinstance(member.units, UnitsCategory)
            else f"units ``{member.units.fixed}``"
        )
    if member.shape is not None and (
        member.shape.dims is not None or member.shape.rank is not None
    ):
        dims = ", ".join(
            (
                "*"
                if d is None
                else str(getattr(d, "expr", None) or getattr(d, "value", None) or d)
            )
            for d in member.shape.dims or []
        )
        shape = (
            f"[{dims}]"
            if member.shape.dims is not None
            else f"rank {getattr(member.shape.rank, 'expr', member.shape.rank)}"
        )
        parts.append(
            f"shape {shape}" + ("" if member.shape.binding else " (illustrative)")
        )
    parts.append(f"*{_requirement(member)}*")
    lines = [f"{indent}- {head}: {', '.join(parts)}"]
    notes = []
    if member.declared_by != owner:
        notes.append(f"inherited from :ref:`{member.declared_by}`")
    if member.refines:
        notes.append(f"refines ``{member.refines}``")
    refined = [c for c in member.refined_by if c != member.declared_by]
    if refined:
        notes.append("refined by " + ", ".join(f":ref:`{c}`" for c in refined))
    if member.provisional:
        notes.append(f"*provisional:* {', '.join(member.provisional)}")
    if isinstance(member, ResolvedChild) and member.target:
        notes.append(f"link to ``{member.target}``")
    if notes:
        lines += ["", f"{body}" + "; ".join(notes)]
    if member.deprecated:
        lines += ["", f"{body}**Deprecated:** {_one_line(member.deprecated)}"]
    if member.enum is not None:
        values = ", ".join(f"``{v.value}``" for v in member.enum.values)
        lines += [
            "",
            f"{body}{'Suggested' if member.enum.open else 'Allowed'} values: {values}",
        ]
    doc = bundle.doc(member.docs[-1]) if member.docs else None
    if doc:
        lines += [""] + [f"{body}{line}" if line else "" for line in doc.splitlines()]
    lines.append("")
    if isinstance(member, ResolvedChild):
        if member.attributes:
            lines += _members(bundle, owner, member.attributes, [], [], depth + 1)
        if member.specialisation and member.specialisation.startswith(owner + "/"):
            spec = bundle.group(member.specialisation)
            if spec is not None:
                own = [
                    m for m in spec.children if owner in (m.declared_by, *m.refined_by)
                ]
                own_attributes = [
                    a
                    for a in spec.attributes
                    if owner in (a.declared_by, *a.refined_by)
                ]
                other = (
                    len(spec.children)
                    + len(spec.attributes)
                    - len(own)
                    - len(own_attributes)
                )
                lines += _members(
                    bundle, owner, own_attributes, own, spec.require, depth + 1
                )
                if other:
                    lines += [
                        f"{body}- … and {other} members of :ref:`{spec.class_}`",
                        "",
                    ]
    return lines


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _index(bundle: BundleReader) -> str:
    lines = ["NeXus classes (NXDS)", "====================", ""]
    lines += [f"Rendered from the NXDS bundle of release {bundle.index.release}.", ""]
    by_status: dict[str, list[str]] = {}
    for name, resolved in bundle.index.classes.items():
        by_status.setdefault(resolved.status, []).append(name)
    for status, title in _STATUS_TITLES.items():
        names = sorted(by_status.get(status, []))
        if not names:
            continue
        lines += [title, "-" * len(title), "", ".. toctree::", "   :maxdepth: 1", ""]
        lines += [f"   {n}" for n in names]
        lines.append("")
    return "\n".join(lines) + "\n"
