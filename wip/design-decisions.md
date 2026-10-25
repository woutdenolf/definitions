# NXDS prototype — design decisions (working document)

This file collects the decisions the prototype implements. It is the input for
`nxds_tools` and for the proposal (`wip/proposal.md`). Every decision marked
**(Dn)** is provisional: the NIAC decides it (see the proposal, section "Open
questions"). The prototype implements the stated default and records the
dependency in the output (`provisional: [Dn]`).

Sources: the definitions repository (main, open PRs and issues), the NeXus wiki,
`nexusformat_pydantic`, the validators in `../validators`, and six rounds of
review of the proposal.

## 1. Repositories and files

- `nxds_tools` (new, independent Python project in the subfolder `nxds_tools/` of the definitions repository, with its own `pyproject.toml`; not the existing `dev_tools`):
  - `nxds_tools.nxdl`: read NXDL (lxml), apply the translation rows, produce the
    NXDS *source form* of each class.
  - `nxds_tools.source`: read and write NXDS source form (YAML).
  - `nxds_tools.resolve`: source forms → *resolved form* (one JSON file per class)
    and the *bundle* (one JSON with everything).
  - `nxds_tools.model`: pydantic models of the source form and of the resolved form;
    their JSON Schemas are the metaschema (`nxds_tools schema`).
  - `nxds_tools.translation`: the translation rows as data (id, NXDL side, NXDS side,
    decision it depends on); `nxds_tools translation-table` renders them as Markdown.
  - `nxds_tools.to_nxdl`: NXDS source → NXDL (for the legacy artifact and the
    round-trip check of phase 2).
  - `nxds_tools.validate`: lazy HDF5 validator driven by the bundle (findings as JSON lines).
  - `nxds_tools.docs`: render class documentation (reStructuredText) from the resolved form.
  - CLI: `python -m nxds_tools {build,check,validate,docs,schema,translation-table,to-nxdl}`.
- definitions branch `nxds` (worktree `/home/denolf/projects/nexus/definitions_nxds`):
  - `make nxds` runs `nxds_tools build` → writes `nxds/generated/`.
  - CI (`.github/workflows/nxds.yaml`) runs `make nxds` and fails if anything
    under `nxds/generated/` changes (the generated files must be committed with
    the PR), and fails on build errors.
  - `nxds/generated/source/<category dir>/<NXclass>.nxds.yaml`: the source form
    *translated* from NXDL (only for classes written in NXDL).
  - `nxds/generated/resolved/<NXclass>.json`: the resolved form, one file per class
    (pull requests show the change of meaning as a readable diff).
  - `nxds/generated/translation.md`, `nxds/generated/schema/*.json`.
  - The combined bundle `nxds-<release>.json` is built at release time from the same command.
  - Phase-2 classes are written as `<category dir>/<NXclass>.nxds.yaml` next to the NXDL files.
  - `wip/`: proposal, slides, this file.

## 2. Data model

- A data tree: groups (with a class), datasets (value: type + shape), attributes
  (small value on a group or dataset), links (an entry that stands for another
  object, in the same or another file).
- NeXus is independent of the storage format. A **storage profile** says how the
  tree is stored in a given format: HDF5 (main), Zarr, nexus-json/silx-dictdump
  (in memory). Profile = data: name of the class attribute (`NX_class`), name of the
  units attribute (`units`), how links are represented and recognised, which
  storage types satisfy each NeXus type, the entry points for dispatch, the release
  attribute.

## 3. Classes and members

Class keys: `class`, `category` (base|application), `status` (from the
directory: base_classes→`base`, applications→`application`,
contributed_definitions→`contributed`, a dormant/stagnant subdirectory→`dormant`;
documentation only), `extends`, `describes` (application definitions: `NXroot`),
`defaults` (source only), `symbols`, `children`, `attributes`, `require`,
`undeclared`, `deprecated`, `doc`, `lossy` (bundle only).

Member keys (resolved form, all explicit): `id`, `node`, `name` (matcher),
`occurs {min, max}`, `recommended`, `class`, `specialisation`, `type`, `shape`,
`units`, `enum`, `length`, `names_child`, `attributes`, `target`, `rules`,
`deprecated`, `doc`, `docs` (list of `{by, text}` from each declaring/refining
class), `show` (documentation only, from `reused_concepts` #1650), `declared_by`,
`refined_by`, `provisional`, `via`.

### Ids (Q11)
- Children of a group are identified by `(id, node kind)`. A dataset member and a
  group member may share an id: they are alternative forms of one item (NXsample
  `magnetic_field` dataset or NXlog group; NXdata's own `DATA` dataset and the
  `DATA` group inherited from NXobject). A file can only contain one of them.
- Attributes have their own namespace.
- T2 ids for unnamed groups: class name without `NX`, upper case.
- Two members with the same `(id, kind)` from *different* declarations in the same
  class are a compile error.

## 4. Matching (how objects in a file are assigned to members)

Name members: `{exact: n}`, `{template: "{AXISNAME}_indices"}`, `{any: true}`.
Roles: `{ref: "@signal"}` (additive).

Assignment for each object in a group:
1. candidates = name members of the same node kind whose matcher accepts the name
   (a link: `link` members and members of the target's kind). For groups,
   `template`/`any` also require the object's class to equal the member's class or
   a subclass (Q4). `exact` does not filter on class (mismatch → `CLASS`).
2. choose: exact first; then members declared/refined by the most derived class;
   then template (most fixed characters) before any; then most specific class; then
   first listed.
3. all objects assigned, then occurrence checked (no fall-through).
4. Several `any` members of the same node kind in one class: compile warning
   (except roles produced by T13).

### Name-fit refinement (Q4)
- An exact-named member written in a subclass or application definition that fits
  an inherited `template`/`any` member of the same node kind (and class, for groups)
  **refines** that member: it inherits its declarations (type, units, attributes, doc)
  and adds or overrides its own. This is what `dev_tools/utils/nxdl_utils.py`
  (`get_nx_namefit`, `walk_elist`) and the documentation's "inherited from" links do
  today. When several inherited members fit, the best fit wins (exact text length
  of the template, then order); ties are a compile warning.
- `field/@extends` (#1533), if merged, names the refined member explicitly and wins.

## 5. Refinement rules (Q4)

- Allowed: raise `min`, lower `max`, add shape/units/attributes/children, add
  `deprecated`, change `doc` (resolved `docs` keeps all), restrict `enum`, narrow `type`.
- Replacing an `enum` with one that is not a subset, or changing `type` to one that
  is not narrower: allowed with a resolution **warning** (corpus: NXarpes
  `acquisition_mode`, NXguide `*_indices`).
- Application definition extending another one: the `definition` dataset's
  enumeration is **replaced** without warning (T8b).
- Widening `occurs` (lower `min`, higher `max`) is a warning too (provisional).

## 6. Dispatch, releases, links (Q8, Q9)

- Entry points: `NXentry`, `NXsubentry` (profile data). An entry point with a
  `definition` naming an application definition is checked against that
  definition's entry member (whatever its class). Other entries: base class only.
- An entry may name only one definition today (#1443 asks for several: Q9).
- `definition/@version`, `@URL` (and `@revision`, #937) are informative only.
- `expect: NXfoo` option → `NO-DEFINITION`.
- Release: root `@NeXus_release`; else caller's choice, default newest.
- Links: the default follows the manual at compile time (storage: soft, external,
  hard + `@target`). #1669 would change it to "by content (a copy with `@target`
  is a link)" — Q8.
- A link assigned to a member: the member's checks apply to the target's metadata,
  reported at the link path. A group reached through an internal link is checked
  against the specialisation of the member it is assigned to (members only, not
  undeclared content), and also where it lives. A group reached through an
  external link is descended into (master files). Objects visited once (file +
  object identity).

## 7. Types, shapes, units

- Types: lattice from `nxdlTypes.xsd`; HDF5 storage table (Q7) as in the proposal.
- Shapes: `shape: {rank?, dims?: [entry...], binding}`; dim entry = integer |
  symbol | `null` | `{expr: "tof+1"}` (sum of symbols and integers, `2n` style
  products allowed) | `{optional: true, value: ...}` (NXDL `dim/@required="false"`).
  `rank` = integer | symbol | `null`. Undeclared symbols: compile warning (lint).
- Units: category → *set* of dimensions (NX_FLOW: volume/time or mass/time) and
  examples; `{fixed: eV}`.
- Enumerations: `{values: [{value, doc?, deprecated?}], open}`; NXDL item values are
  parsed with the member's type (numbers stay numbers, #1235); wildcard items like
  `image/*` are kept as literal values with a compile warning (#1234, provisional).

## 8. Translation rows (T)

T0 XSD defaults · T1 element kinds · T2 unnamed groups · T3 nameType partial ·
T3b upper case without nameType: exact, lint warning (#1490) · T4 base min ·
T5 application min (attributes and links included, Q2) · T6 precedence ·
T7 max · T8 extends/describes · T8b replaced `definition` enum · T9 dimensions
(T9a binding by category, T9b expressions, T9c optional dims, T9d symbolic rank) ·
T10 link targets · T11 choice · T12 ignoreExtra* → undeclared: ignore ·
T13 class-specific roles (NXdata DATA/AXISNAME/auxiliary_signals,
NXobject @default) · T14 `reused_concepts`/`reused_from` → documentation only
(#1650) · T15 `fieldAttributes` (#1669, if merged) · T16 `valueFrom="class"` →
profile class attribute (#1669) · T17 directory → status ·
T18 name-fit refinement.

## 9. Findings

As in the proposal: codes with separate severity, conformance tuple
`(code, severity, path, member)`, tiers M/S/F, partial mode.

## 10. Versioning

- NXDS language `0.x` until the NIAC adopts 1.0; no compatibility promise before.
- Bundle `nxds-<release>-r<revision>.json`, index with status.
