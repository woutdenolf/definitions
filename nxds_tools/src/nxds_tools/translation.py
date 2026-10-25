"""The NXDL → NXDS translation rows, as data."""

from pydantic import BaseModel
from pydantic import ConfigDict


class Row(BaseModel):
    """One translation row: what an NXDL construct means in NXDS."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    nxdl: str
    nxds: str
    depends_on: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


DECISIONS: dict[str, str] = {
    "Q1": "Occurrence defaults and precedence (minOccurs, optional, recommended)",
    "Q2": "Attributes and links are required by default in an application definition",
    "Q3": "Placeholder characters; may a placeholder be empty; template priority",
    "Q4": "Refinement: override or extend; subclasses where a superclass is expected; name-fit",
    "Q5": "Are shapes binding; scope of a symbol",
    "Q6": "Severities of findings",
    "Q7": "NeXus type to storage types",
    "Q8": "Links: by storage or by content; is a copy acceptable",
    "Q9": "Dispatch: entry points, definition, NXsubentry, root-level members",
    "Q10": "A standard way to mark an entry as aborted or incomplete",
    "Q11": "Ids: a dataset member and a group member may share an id",
    "Q12": "The rules of NXdata and NXobject written in the manual become roles and "
    "names_child (T13): DATA named by @signal, AXISNAME by @axes, @auxiliary_signals "
    "names datasets, @default names a group; AXISNAME_indices and the other rules of "
    "the manual are not checked",
    "Q13": "Reserved prefixes and suffixes (not checked: NXDS states no rule for them)",
    "Q14": "A free-named member of a specialisation applies to every object it "
    "matches (a free-named NXdata member of an entry specialisation applies to every "
    "NXdata group of that entry)",
}

ROWS: tuple[Row, ...] = (
    Row(
        id="T0",
        title="XSD defaults",
        nxdl="an XML attribute that an NXDL element does not write",
        nxds="the XSD default of nxdl.xsd being compiled, unless a later row says "
        "otherwise; the default of `field/@type` and `attribute/@type` becomes "
        "`defaults.type`, so it applies to new members while a refinement "
        "inherits the type of the member it refines",
    ),
    Row(
        id="T1",
        title="element kinds",
        nxdl="`group`, `field`, `link` / `attribute`",
        nxds="a child with `node: group`, `dataset`, `link` / an entry in `attributes`",
    ),
    Row(
        id="T2",
        title="unnamed groups",
        nxdl="`group` without `name`",
        nxds="`name: {any: true}`; id = the class name without `NX`, in upper case "
        "(`NXdata` → `DATA`); a clash with another id of the same kind in the same "
        "parent is a compile error",
        depends_on=("Q11",),
    ),
    Row(
        id="T3",
        title="nameType",
        nxdl='`nameType="partial"` / `nameType="any"`',
        nxds="`name: {template: …}`, each run of upper-case letters becomes a "
        "placeholder `{RUN}` / `name: {any: true}`",
        depends_on=("Q3",),
        references=("#1485", "#1490", "#1475"),
    ),
    Row(
        id="T3b",
        title="upper case without nameType",
        nxdl="a `name` with upper-case letters and no `nameType`",
        nxds="`name: {exact: …}` (the XSD default `specified`), with a lint warning",
        references=("#1490",),
    ),
    Row(
        id="T4",
        title="base min",
        nxdl='the minimum occurrence of a member of a `category="base"` class',
        nxds="T6, falling back to `defaults.min: 0`",
    ),
    Row(
        id="T5",
        title="application min",
        nxdl='the minimum occurrence of a member of a `category="application"` '
        "class, attributes and links included",
        nxds="T6, falling back to `defaults.min: 1`",
        depends_on=("Q2",),
    ),
    Row(
        id="T6",
        title="precedence",
        nxdl="`minOccurs`, `optional`, `recommended`",
        nxds='precedence `minOccurs` > `optional` > `recommended`; `optional="false"` '
        'gives `min: 1`, `optional="true"` gives `min: 0`; `recommended="true"` '
        "gives `min: 0, recommended: true`",
        depends_on=("Q1",),
        references=("#1513", "#1636"),
    ),
    Row(
        id="T7",
        title="max",
        nxdl="`maxOccurs` not written",
        nxds="`max` left to the resolver: 1 for a fixed name, unbounded for a free "
        "name; a refinement inherits it (overrides the XSD default)",
        depends_on=("Q1",),
    ),
    Row(
        id="T8",
        title="extends / describes",
        nxdl="`extends`",
        nxds="a base class without `extends` extends `NXobject`; an application "
        'definition `describes: NXroot` and its `extends="NXobject"` is dropped; '
        "`extends` naming another application definition is kept",
    ),
    Row(
        id="T8b",
        title="replaced definition enumeration",
        nxdl="an application definition extending another one restates the "
        "`definition` dataset with its own name",
        nxds="the enumeration of the profile's dispatch dataset is replaced without "
        "a warning",
    ),
    Row(
        id="T9",
        title="dimensions",
        nxdl="`dimensions`",
        nxds="`shape: {rank, dims}`; `dims` lists `dim/@value` by `@index`, `null` "
        "where none is given",
    ),
    Row(
        id="T9a",
        title="binding by category",
        nxdl="the category of the class",
        nxds="`defaults.binding`: true in an application definition, false in a base "
        "class",
        depends_on=("Q5",),
        references=("#1508",),
    ),
    Row(
        id="T9b",
        title="dimension expressions",
        nxdl='`dim value="tof+1"`, `"2n"`',
        nxds="`{expr: tof+1}`, `{expr: 2*n}` (an implicit product is made explicit, "
        "spaces are removed)",
    ),
    Row(
        id="T9c",
        title="optional dimensions",
        nxdl='`dim required="false"`',
        nxds="`{optional: true, value: …}`",
    ),
    Row(
        id="T9d",
        title="symbolic rank",
        nxdl='`dimensions rank="dataRank"`',
        nxds="`rank: dataRank`; an expression becomes `rank: {expr: 1+dataRank}` "
        "(anything else is dropped with a warning)",
    ),
    Row(
        id="T10",
        title="link targets",
        nxdl='`link target="/NXentry/…/monochromator:NXmonochromator/energy"`',
        nxds="`node: link, target: ENTRY/…/monochromator/energy` (each step `NXclass` "
        "becomes the T2 id, `name:NXclass` becomes `name`); in a base class the path "
        "keeps its leading `/` and starts at the root class",
        depends_on=("Q8",),
    ),
    Row(
        id="T11",
        title="choice",
        nxdl='`choice name="n"` over groups',
        nxds="one group member per alternative, id `n_<CLASS>`, all named `{exact: n}`, "
        "plus `exactly_one_of` (application) or `at_most_one_of` (base) over them",
    ),
    Row(
        id="T12",
        title="ignoreExtra*",
        nxdl='`ignoreExtraGroups/Fields/Attributes="true"`',
        nxds="`undeclared: ignore` for that node kind",
        depends_on=("Q6",),
    ),
    Row(
        id="T13",
        title="class-specific roles",
        nxdl="prose of the manual about `NXdata` and `NXobject`",
        nxds='in `NXdata`: dataset `DATA` → `name: {ref: "@signal"}`, dataset '
        '`AXISNAME` → `name: {ref: "@axes"}`, `@auxiliary_signals` → '
        "`names_child: dataset`; in `NXobject`: `@default` → `names_child: group`",
        depends_on=("Q12",),
    ),
    Row(
        id="T14",
        title="reused concepts",
        nxdl="`reused_concepts` / `reused_from` (#1650, if merged)",
        nxds="`show` (documentation only)",
        references=("#1650",),
    ),
    Row(
        id="T15",
        title="fieldAttributes",
        nxdl="`fieldAttributes` (#1669, if merged)",
        nxds="the attributes are added to every dataset member written in that group",
        references=("#1669",),
    ),
    Row(
        id="T16",
        title="valueFrom",
        nxdl='`valueFrom="class"` (#1669, if merged)',
        nxds="the profile's class attribute; the member is dropped",
        references=("#1669",),
    ),
    Row(
        id="T17",
        title="directory → status",
        nxdl="the directory of the file",
        nxds="`status`: `base_classes` → base, `applications` → application, "
        "`contributed_definitions` → contributed, a dormant/stagnant subdirectory → "
        "dormant (documentation only)",
    ),
    Row(
        id="T18",
        title="name-fit refinement",
        nxdl="a fixed name written in a subclass that fits an inherited `partial`/`any` "
        "member of the same kind (and class, for groups)",
        nxds="a new member with `refines: <label>` of the best fitting one (a `template` "
        "before `any`, more fixed characters first, then member order): placed right "
        "after it, inheriting what it does not state; NXDS classes write `refines` "
        "themselves",
        depends_on=("Q4",),
    ),
    Row(
        id="T19",
        title="legacy field attributes",
        nxdl="`field/@signal`, `@axis`, `@primary`, `@axes`, `@long_name`, "
        "`@interpretation`",
        nxds="an optional attribute member of the dataset with that value as a closed "
        'enumeration; a value with spaces (`". ."`) is a list value, and every '
        "enumeration item of an array-shaped member is split the same way and parsed "
        "with the member's type",
    ),
)

ROW_IDS: frozenset[str] = frozenset(row.id for row in ROWS)


def render_markdown() -> str:
    """The translation table as Markdown."""
    lines = [
        "# NXDL → NXDS translation table",
        "",
        "Generated by `nxds_tools translation-table`. Rows marked with a decision "
        "depend on an open question of the NIAC; values produced by them are marked "
        "`provisional` in the resolved form.",
        "",
        "| Row | Title | NXDL | NXDS | Depends on | References |",
        "|---|---|---|---|---|---|",
    ]
    for row in ROWS:
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                row.id,
                row.title,
                row.nxdl.replace("|", "\\|"),
                row.nxds.replace("|", "\\|"),
                ", ".join(row.depends_on),
                ", ".join(row.references),
            )
        )
    lines += ["", "## Decisions", ""]
    for key, text in DECISIONS.items():
        lines.append(f"- **{key}**: {text}")
    return "\n".join(lines) + "\n"


def sort_rows(rows: "list[str] | set[str]") -> list[str]:
    """Row ids in table order (``T2`` before ``T10``)."""
    order = {row.id: index for index, row in enumerate(ROWS)}
    return sorted(set(rows), key=lambda r: (order.get(r, len(order)), r))


def provisional_for(rows: list[str]) -> list[str]:
    """The decisions a set of rows depends on."""
    by_id = {row.id: row for row in ROWS}
    return sorted(
        {d for r in rows if r in by_id for d in by_id[r].depends_on}, key=_dkey
    )


def _dkey(decision: str) -> int:
    return int(decision[1:])
