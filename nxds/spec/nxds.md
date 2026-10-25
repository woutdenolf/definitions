# NXDS specification — draft 0.1

*NeXus Definition Schema. Working draft 4, October 2026. Not adopted by the NIAC.*

This document defines what an NXDS class means for a NeXus data tree, how classes are
resolved, how a validator assigns objects of a data file to the items of a class, and
what it reports. It is written so that a tool can be built from it without reading the
reference implementation (`nxds_tools`).

The key words MUST, MUST NOT, SHOULD and MAY are used as in
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

Values that depend on a question the NIAC has not answered yet are marked
**(Qn, provisional)**; the questions are listed in the proposal (`wip/proposal.md`, §12).

## Contents

1. [Documents and versions](#1-documents-and-versions)
2. [The data tree](#2-the-data-tree)
3. [Class files (source form)](#3-class-files-source-form)
4. [Members](#4-members)
5. [Resolution](#5-resolution)
6. [The resolved form](#6-the-resolved-form)
7. [Matching objects to members](#7-matching-objects-to-members)
8. [Application definitions and dispatch](#8-application-definitions-and-dispatch)
9. [Checks](#9-checks)
10. [Findings](#10-findings)
11. [Partial mode](#11-partial-mode)
12. [Storage profiles](#12-storage-profiles)
13. [Data types](#13-data-types)
14. [Units](#14-units)
15. [Conformance](#15-conformance)
16. [Translation from NXDL](#16-translation-from-nxdl)

---

## 1. Documents and versions

| Document | Normative | Where |
|---|---|---|
| this specification | yes | `nxds/spec/` |
| metaschema: JSON Schemas of class files, resolved files, the index and findings | yes; the implementation is tested against it | `nxds/metaschema/` |
| conformance suite | yes, as examples of this text; a disagreement between a test and this text is a bug in one of them | `nxds/conformance/` |
| translation table (NXDL → NXDS) | yes, for NXDL sources only | §16 and `nxds/generated/translation.md` |

- **Language version.** Every class file, resolved file and index states `nxds: "<major>.<minor>"`. Before 1.0 (`0.x`) there is no compatibility promise; a tool MUST pin the exact `0.x` version it supports.
- **Features.** Every resolved file lists in `requires` the language features it uses, directly or through references, that are not in the core of its version (§6.4).
- **The metaschema is written by hand.** A change to the language starts with a change to the metaschema and this text; the implementation follows and is tested against them.
- **Releases.** A release of the NeXus classes (`v2026.01`) has one generated bundle per revision: `nxds-v2026.01-r1`, `-r2`, … A revision never changes once published.

## 2. The data tree

A data file holds a tree of:

- **groups**, each with a class;
- **datasets**, each with a value that has a storage type and a shape;
- **attributes**, small values attached to a group or a dataset;
- **links**, entries of a group that stand for a group or dataset elsewhere in the same file or in another file.

The root of the tree is a group of the class named by the profile's `root_class` (`NXroot`).

Names of groups, datasets and links in one group share one namespace. Attributes of one object form a separate namespace.

## 3. Class files (source form)

A class file is a YAML (or JSON) document. Its format is defined by `nxds/metaschema/source.json`. Top-level keys:

| Key | Required | Meaning |
|---|---|---|
| `nxds` | yes | language version |
| `class` | yes | the class name; equals the file name without `.nxds.yaml` |
| `category` | yes | `base` or `application`; documentation only in NXDS sources (for NXDL sources the translation uses it, §16) |
| `extends` | no | the parent class |
| `describes` | application definitions | the class of the root it describes (`NXroot`). A class with `describes` is an **application definition**; `category` does not change meaning |
| `defaults` | yes | see §3.1 |
| `doc` | no | documentation |
| `symbols` | no | `{name: {doc}}`: lengths shared by shapes in this class |
| `children` | no | `{label: member}`: groups, datasets and links |
| `attributes` | no | `{label: member}`: attributes of the group |
| `require` | no | constraints between members (§9.6) |
| `undeclared` | no | `report` (default), `ignore` or `error`, or a map per kind `{group, dataset, attribute}` |
| `deprecated` | no | a message |

### 3.1 Defaults

`defaults` MUST be present. Keys:

| Key | Required | Applies to | Meaning |
|---|---|---|---|
| `min` | yes | every member written in this file, including members that refine an inherited one | the minimum number of occurrences when the member does not state `occurs.min` |
| `binding` | yes | every shape written in this file | `true`: shapes are rules; `false`: shapes are examples (not checked) |
| `type` | no | every dataset or attribute member written in this file that does not refine an inherited member and states no `type` | the data type; when absent, `NX_CHAR` |

A new member (one that refines nothing) without `occurs.max` gets `max: 1` for an `exact` name and `unbounded` for `template` and `any` names. A file holds at most one object with a given name, so an `exact`-named member with `max` above 1 is a resolution warning (the value is kept, it cannot be exceeded). A member with `refines` that has an `exact` name gets `max: 1` unless it states one.

A member that refines an inherited member keeps the inherited `type`, `units`, `enum`, `shape` and `doc` unless it states them. When it does not state `occurs.min`, it takes its own file's `defaults.min`, but never less than the inherited minimum. When it does not state `occurs.max`, it keeps the inherited maximum. A value that it states is used as stated, also when it widens (§5.2.6).

## 4. Members

A member is one item a class declares. It is written under a **label** (the key in `children` or `attributes`).

### 4.1 Keys

| Key | Members | Meaning |
|---|---|---|
| `node` | children | `group`, `dataset` or `link` |
| `name` | all | the matcher (§4.2); default `{exact: <label>}` |
| `occurs` | all | `{min, max}`; `max` is an integer or `unbounded` |
| `recommended` | all | `true`: absence is reported as `RECOMMENDED`; only with `min: 0` (with `min` ≥ 1 it is a resolution warning and has no effect) |
| `class` | groups | the class of the group |
| `type` | datasets, attributes | the data type (§13) |
| `shape` | datasets, attributes | §4.4 |
| `units` | datasets | `{category: NX_…}` or `{fixed: "…"}` (§14) |
| `enum` | datasets, attributes | allowed values (§4.5) |
| `target` | links | a label path (§4.6) |
| `refines` | children, attributes | the label of an inherited member this member refines (§5.2) |
| `names_child` | attributes | `group` or `dataset`: the attribute's value names a child of that kind (§9.5) |
| `length`, `rank` | attributes | constraints on an array-valued attribute (§9.6) |
| `children`, `attributes` | groups, datasets (`attributes` only) | members of a specialisation (§5.3) or attributes of a dataset |
| `deprecated` | all | a message; presence of the object is reported as `DEPRECATED` |
| `doc` | all | documentation |

### 4.2 Name matchers

| Matcher | Matches a name *n* if |
|---|---|
| `{exact: "e"}` | *n* = e |
| `{template: "{A}_indices"}` | *n* is the template with every placeholder `{X}` replaced by a non-empty string of characters from the profile's `placeholder_characters` (Q3, provisional) |
| `{any: true}` | *n* is any valid name (§4.3) |
| `{ref: "@a"}` | *n* is a value of the attribute `a` of the parent group (a **role**, §7.4) |

Placeholders are anonymous in 0.1: nothing checks that `{A}` names an existing sibling.

**Fixed characters** of a template: the number of characters outside placeholders.

### 4.3 Valid names

A name is valid if it matches the index's `names.item_pattern` (an [I-Regexp](https://www.rfc-editor.org/rfc/rfc9485), implicitly anchored) and has at most `names.item_max_length` characters (Unicode code points). An invalid name is reported as `NAME`; the object is still matched.

### 4.4 Shapes

`shape` is a list (shorthand for `{dims: [...]}`) or an object `{rank, dims, binding}`:

- `rank`: an integer, a symbol or `{expr: "e"}`: the number of dimensions.
- `dims`: one entry per dimension, in order. Each entry is one of:
  - an integer;
  - a symbol name;
  - `null`: any length;
  - `{expr: "e"}`: an expression of symbols and integers with `+`, `-` and `*`, for example `tof+1`, `2*n` (NXDL `2n` is translated to `2*n`);
  - `{optional: true, value: <entry>}`: the dimension may be absent; optional dimensions MUST come after all required ones.
- `binding`: taken from `defaults.binding` of the file that writes the shape. An inherited shape that a refinement does not restate keeps the binding of the file that wrote it.
- `symbols` (resolved form only): `{symbol: declaring class}` for every symbol the shape uses.

No `shape` means any shape. `[]` means a scalar.

### 4.5 Enumerations

`enum` is a list (shorthand for `{values: [...], open: false}`) or `{values, open}`. A value is a scalar, a list, or `{value, doc, deprecated}` (where `value` is a scalar or a list).

- Values are written with the member's type: numbers as numbers, text as text.
- A scalar value applies to **each element** of an array. A value that is a list applies to the **whole array** (for example `[".", "."]` for a two-element `@axes`).
- `open: true`: other values are allowed and reported as `ENUM-OPEN` (W).
- A deprecated value that is used is reported as `DEPRECATED`.

### 4.6 Label paths

`target` (and the member references of §6.3) use **label paths**: labels separated by `/`, starting at the class that contains the member, for example `ENTRY/INSTRUMENT/monochromator/energy`. In a specialisation, the first step is the dispatched group's member (`ENTRY`). A path that starts with `/` starts at the root class (used by base classes, whose NXDL targets are absolute).

A step MAY be followed by `[group]` or `[dataset]` (a link member has the dataset or group form of its target). The suffix is REQUIRED when a group member and a dataset member of the same parent share a label (§5.1).

A step matches a member with that label, or a member that `refines` it; the path then continues in the specialisation of the member that applies.

## 5. Resolution

Resolution turns class files into the resolved form (§6). It is defined by this section; the conformance suite (§15) has examples.

### 5.1 Identity

- A child member is identified by **(label, form)**, where the form is `group` for group members, `dataset` for dataset members, and for a link member the form of its target (resolved from the label path at resolution time; if the target cannot be resolved, `dataset` and a resolution warning). A group member and a dataset member MAY share a label (Q11, provisional): they are two forms of one item; a data file contains one of them, and occurrences are counted over both forms together (one `MISSING` per item, with the member of the form listed first in *M*).
- A link member with the label of an inherited member of the same form refines it (it says: this item must be a link).
- Roles (§7.4) are not part of this identity: a role never shares an item with a member that has the same label.
- An attribute member is identified by its label.
- Labels are identity: a member refines an inherited member if and only if it has the same identity, or names it with `refines`. Upper-case labels for free names are a convention; they have no other meaning.

### 5.2 Inheritance

1. `extends` names one parent; cycles are an error. A base class without `extends` extends `NXobject`, except `NXobject` itself and the root class.
2. An application definition with `describes: C` inherits the members of `C` as if `C` were its parent; with `extends: A` it inherits `A` (which itself describes `C`).
3. The members of a class are the members of its parent, in the parent's order, followed by the members the class adds, in the order they are written.
4. A member with the identity of an inherited member **refines** it: it takes the inherited member's place in the order, and the keys it does not state are inherited (§3.1).
5. A member with `refines: L` refines the inherited member with label `L` (and the same node). It is added as a new member right after `L` and after members that refine `L` and were written before it. Objects assigned to it also count towards `L`'s occurrences.
6. **Narrowing.** A refinement SHOULD only narrow: raise `min`, lower `max`, narrow `type`, restrict `enum`, add `shape`, `units`, attributes or children. A refinement that states a wider value is a resolution warning; the stated value is used (Q4, provisional).
7. **Enumeration values of NXDL sources** are typed after the steps above, with the member's resolved type and shape: values are parsed as the type's values, for an array-shaped text member a value containing spaces (`". ."`) becomes a list, and for an array-shaped numeric member a value written as a list (`[0, 0, 1]`) becomes a list of numbers (§4.5).

### 5.3 Specialisations

A group member that states `children` or `attributes` defines a **specialisation**: the member's class, refined by those members. Its id is the name of the class that writes it followed by the label path, for example `NXdemo_phase2/ENTRY/DATA` or `NXdetector/efficiency`. Specialisations nest. Base classes may define specialisations too.

## 6. The resolved form

The resolved form is generated (`nxds/generated/resolved/<class>.json`); its format is defined by `nxds/metaschema/resolved.json`.

### 6.1 Contents

One file per class:

```json
{"nxds": "0.1", "requires": [], "definition": {…}, "specialisations": {"<id>": {…}}}
```

`definition` and each specialisation list all members, inherited ones included, in the order of §5.2.

### 6.2 Members in full

A member that the class or specialisation declares or changes is written in full, with every key explicit (no defaults, no shorthands), plus:

- `id`: the label;
- `declared_by`: the class that first declared the identity;
- `refined_by`: the classes that refined it, in order;
- `specialisation`: for a refined group member, the id of its specialisation.

### 6.3 Member references

A member the class inherits without change is written as a reference: `{"ref": "<scope>/<label path>", "node": "<node>"}` (children) or `{"ref": "<scope>@<label>"}` (attributes). The referenced member is written in full in the resolved file of `<scope>` (a class or specialisation).

- A reference MUST resolve to a member written in full (references are never chained).
- `<scope>` is the longest prefix that is a class name or a specialisation id; the rest is the label path.

### 6.4 Features

The core of 0.1 is everything in this specification: all matchers including roles, `occurs`, `recommended`, `deprecated`, `refines`, `undeclared`, `type`, `shape` (including expressions, optional dimensions and symbolic ranks), `enum`, `units` (category and fixed), links, `names_child`, `require`, attribute `length` and `rank`, specialisations, references, and `show` and `doc` (documentation only). `requires` is therefore empty in 0.1, and so is the index's `features` list.

Later versions add features with an id (for example `require.if`). A tool that does not know a feature listed in a file's `requires` reports `SKIPPED` once for every class or specialisation that uses it, and does not check their members.

### 6.5 The index

`nxds/generated/index.json` (format: `nxds/metaschema/index.json`) holds: the language version, the release and revision, the list of classes with `category`, `status`, `extends` and `describes`, the data types (§13), the units categories (§14), the name rules (§4.3), the profiles (§12), the codes (§10) and the open questions.

## 7. Matching objects to members

For each group *G* of a data file, the validator determines the member list *M* that applies to *G* (its class, or a specialisation, §8). Each child object *o* of *G* is assigned as follows.

### 7.1 Kind

| Object | Can be assigned to |
|---|---|
| group | group members |
| dataset | dataset members |
| link to a group / dataset | link members, and group / dataset members |
| dangling link | link members only |

A link member accepts only links (§9.8).

How a link is recognised is defined by the profile (§12).

### 7.2 Candidates

A member *m* is a candidate for *o* if the kind fits (§7.1), the name matcher of *m* matches the name of *o* (roles excluded), and, for group members, the class of *o* is the class of *m* or a subclass of it. A group whose class is not in the bundle, or that has no class, is a subclass of nothing.

### 7.3 Choice

1. If there are candidates, *o* is assigned to the best candidate by these keys, in order:
   1. matcher: `exact` before `template` before `any`;
   2. for templates: more fixed characters first;
   3. a member with `refines` before the member it refines;
   4. for a link object: a link member before a dataset or group member;
   5. order in *M* (also when two templates have the same number of fixed characters).
2. If there are no candidates, but there are group members with an `exact` matcher for the name of *o* whose class does not fit, *o* is assigned to the first of them and reported as `CLASS` (or `NO-CLASS` if *o* has no class). Its children are then checked against its own class; a group without class has no members, so its children are undeclared (policy of the parent's class).
3. Otherwise *o* is **undeclared** (§9.7).

All objects of *G* are assigned before occurrences are counted (§9.1). There is no fall-through to another member when a member is full.

### 7.4 Roles

A member with `name: {ref: "@a"}` is a **role**. Roles are not used for assignment. After assignment:

- every value of the attribute `a` of *G* (one value, or each element of an array; the value `.` is skipped) names a child of *G*;
- that child *fills* the role, in addition to its own member;
- the checks of the role (§9) apply to the child as well, reported with the role's member reference;
- a value that names no child is reported as `REF`;
- `occurs` of a role is not checked.

A child that fills a role is not undeclared. The child MUST be of the role's node kind (a link counts as its target's kind); otherwise `REF`. A dangling link, or a link into a file that cannot be opened, fills the role without checks (it is reported as a link, §9.8).

## 8. Application definitions and dispatch

1. The root is checked against the root class.
2. A group whose class is one of the profile's `entry_points` (`NXentry`, `NXsubentry`) and that has a child named by the profile's `dispatch_dataset` (`definition`) with one text value *d*:
   - if *d* names an application definition *A* of the bundle, the group is checked against one dispatch member of *A* (item 3): among those whose class is the group's class or a superclass of it, the one chosen by §7.3; if there is none, the first dispatch member of *A* (entry points stand in for each other); its specialisation applies;
   - otherwise the group is checked against its class, and *d* is reported as `UNKNOWN-DEFINITION`.
3. Members that an application definition declares or refines and whose class is an entry point are **dispatch members**. A dispatch member of *A* is a candidate only for groups dispatched to *A* (or to an application definition that extends *A*), whatever its name matcher says.
4. **Exception: entries of another definition.** A dispatch member whose specialisation restricts `definition` to other values is a candidate for groups dispatched to those values. Example: *A* requires a subentry that follows *B*; a subentry with `definition = B` fills that member of *A* (it counts for its occurrences) and is checked against *B* only (the member's own specialisation does not apply). Inherited entry-point members that no application definition declares or refines (for example `NXentry/SUBENTRY`) stay ordinary members. A group of an entry-point class without its own `definition`, inside a group dispatched to *A*, counts as dispatched to *A*, also for the root-level counts of item 6.
5. Every other member of a specialisation applies to every object it matches (Q14, provisional). Example: a free-named `NXdata` member of an entry specialisation applies to every `NXdata` group of that entry.
6. For each application definition *A* that at least one group (at any depth) is dispatched to, the root is also checked against the root-level members that *A* (or a definition *A* extends) declares or refines: attributes, and occurrences of dispatch members, counting groups dispatched to *A* or to a definition that extends *A*. Findings use path `/` and member `A/<label>`.
7. **Objects of a subclass.** A group assigned to a member whose class is a superclass of the group's class is checked against the member's specialisation (or class); children and attributes that it leaves undeclared are then matched against the group's own class, and only the checks of the members they are assigned to apply (no occurrence or `require` checks of the own class) (Q4, provisional). Member definitions are never merged.
8. **Expected definition.** A validator MAY be told that a file must follow *A* (`expect`). Then, if fewer groups are dispatched to *A* than *A*'s dispatch members require (at least one), `NO-DEFINITION` is reported at the root, with severity E. Without `expect`, a file in which no group is dispatched gets `NO-DEFINITION` with severity I; with `expect` this I finding is not reported.
9. A `definition` that is not a dataset with one text value is reported as `TYPE` with the member of the group's class (for example `NXentry/definition`).

## 9. Checks

All checks use only metadata and small values (tiers M and S, §9.9) unless stated.

### 9.1 Occurrence

For each member *m* of *M* (roles excluded), count the objects assigned to *m* and to the members that refine it with `refines`:

- fewer than `min`: `MISSING` (or `RECOMMENDED`, W, when `min` is 0 and `recommended` is true and the count is 0);
- more than `max`: `TOO-MANY`;
- more than 0 with `max: 0`: `TOO-MANY`.

A missing group is not entered: members of a missing group are not reported.

### 9.2 Type

The storage type of a dataset or attribute MUST be one of the storage types the profile accepts for the member's type (§12, §13). Otherwise `TYPE`.

Value checks (tier S for one value, tier F for arrays): `NX_POSINT` ≥ 1; `NX_BOOLEAN` integers are 0 or 1; `NX_DATE_TIME` matches §13.2.

### 9.3 Shape

- With `binding: true`: the rank and every integer dimension MUST match; `null` matches any length; an optional dimension may be absent.
- A scalar where `[1]` is declared, or the reverse: `SHAPE`, W. Any other mismatch: `SHAPE`, E.
- **Symbols.** A symbol has one value per instance of the outermost dispatched group (the entry); outside dispatched groups, per file (reported at `/`). All binding uses of the symbol in that entry MUST agree, and expressions MUST hold. A conflict is reported once per symbol and entry: `SHAPE` at the entry, member `<declaring class>#<symbol>`. An expression that fails is reported as a conflict of its first symbol; it is not evaluated while a symbol it uses is unbound or already in conflict.
- Symbols are scoped by the class that declares them: a symbol of a base class is a different symbol from a symbol with the same name in an application definition.
- With `binding: false`, nothing is checked.

### 9.4 Enumeration

Numbers are compared after converting the enumeration value to the stored type. A value not in a closed enumeration: `ENUM`. Not in an open one: `ENUM-OPEN`.

### 9.5 Names of children

An attribute with `names_child: k` MUST have values that name existing children of kind *k*. Otherwise `REF`.

### 9.6 Constraints

- `require: {at_least_one_of: [labels]}` (and `exactly_one_of`, `at_most_one_of`, `all_or_none`): a listed member is *present* if at least one object is assigned to it or to a member that refines it; the constraint counts present members (`all_or_none`: all present or none). Failure: `CONSTRAINT`, member `<scope>:<kind>[<labels joined by ,>]`.
- Attribute `length: n` (or a symbol, or `{rank_of: <role label>}`): the number of elements. `rank: n`: the number of dimensions. Failure: `CONSTRAINT` at the object that owns the attribute, member `<…>@<label>:length` (or `:rank`).

### 9.7 Undeclared objects

An object that is assigned to no member and fills no role is undeclared: `UNDECLARED`, I, unless the applying `undeclared` policy is `ignore` (nothing) or `error` (E). Attributes of datasets follow the dataset's group policy for attributes. A link follows the policy of its target's kind; a dangling link the policy for datasets. Attributes named by the profile (`class_attribute`, `units_attribute`, `link_target_attribute`, `release_attribute`) are never undeclared.

### 9.8 Links

- A link member's `target` is a label path (§4.6). The object the link points to MUST be assigned to the member reached by that path (or to a member that refines it), within the same instance of the nearest group that contains both the link and the target; any instance of a free-named group below it is acceptable. Otherwise `LINK`.
- A dangling link inside an opened file: `LINK`. A link into an external file that cannot be opened is not dangling: it counts as present for occurrence and its checks are `SKIPPED`. Its kind and class are unknown, so it is a candidate only for members with an `exact` or `template` matcher (of any kind); if there are several, the first in *M* (this replaces the keys of §7.3). A known consequence: a link to a free-named member (for example an `NXdata` with any name) in an unopenable file leaves that member `MISSING`.
- When a link is assigned to a group or dataset member, the checks of that member apply to the object the link points to and are reported at the **link's path**. The object is also checked where it lives, against the member it is assigned to there. Both sets of findings are reported.
- A group reached through a link inside the same file is not walked into, except to apply the members of the assigned member's specialisation. A group reached through an external link is walked into as part of the file that links to it.
- Every object is walked once, identified by its file and object identity. An object with several paths is walked at its **own path**: for hard links, the path whose `target` attribute equals itself; otherwise the first path in byte order of the UTF-8 path (finding it can cost one extra metadata walk of the file; writers SHOULD set `target` on hard links). At its other paths it gets only the checks of the member (and specialisation) it is assigned to there.

### 9.9 Tiers

| Tier | Reads | Checks |
|---|---|---|
| M | names, classes, link kinds, storage types, shapes, attributes and their values | everything except value checks of datasets |
| S | datasets with one element | `definition`, enumerations, `NX_POSINT`, `NX_BOOLEAN`, `NX_DATE_TIME` (attributes: always, at tier M) |
| F | all elements of larger datasets | the S checks on every element |

M and S are required. F is optional; without it, the checks are reported as `SKIPPED` once per member. (The reference implementation does not implement F yet.)

### 9.10 Read errors

A failure to read an object (unknown storage type, missing compression filter, unreadable attribute) MUST NOT stop the validation: it is reported as `SKIPPED` for the checks that need it.

## 10. Findings

### 10.1 Format

One JSON object per finding (format: `nxds/metaschema/finding.json`):

| Key | Required | Meaning |
|---|---|---|
| `code` | yes | §10.3 |
| `severity` | yes | `E`, `W` or `I` |
| `path` | yes | the path in the file, `/`-separated; `@a` for an attribute (`/entry/data@signal`; an attribute of the root is `/@default`) |
| `member` | yes, or `null` for undeclared objects | the member reference (§10.2) |
| `bundle` | yes | `<release>-r<revision>` |
| `message`, `expected`, `actual` | no | for people |

A validator SHOULD write findings as soon as they are known (streaming), one per line. The same finding can be reported more than once (for example at a link path and at the object's own path); conformance compares sets.

### 10.2 Member references

```
member     = scope ( "/" step )* [ "@" label ] [ ":" constraint ]
           | class "#" symbol
constraint = ( "at_least_one_of" | "exactly_one_of" | "at_most_one_of" | "all_or_none" ) "[" label ( "," label )* "]"
           | "length" | "rank"
scope      = class name | specialisation id
step       = label [ "[" ( "group" | "dataset" ) "]" ]
```

Labels inside a constraint MAY carry the same suffix. A role never carries a suffix.

The scope is the class or specialisation that applies to the group in which the object is assigned (for `MISSING`: the parent). A kind suffix is written only when needed (§4.6). For a role, the member is the role's.

### 10.3 Codes

| Code | Severity | Path | Partial mode (§11) | When |
|---|---|---|---|---|
| `MISSING` | E | the parent | INCOMPLETE | fewer objects than `min` (one finding per member and parent) |
| `TOO-MANY` | E | the parent | — | more objects than `max` |
| `CLASS` | E | the object | — | a group assigned by an exact name has a class that does not fit |
| `NO-CLASS` | W (Q6) | the object | INCOMPLETE | a group (not the root) has no class |
| `TYPE` | E | the object | — | storage type of the value (or of its elements) not accepted, or a value check failed |
| `SHAPE` | E; W for scalar against length 1 | the object; the entry for symbols | INCOMPLETE if a dataset involved can still grow | §9.3 |
| `ENUM` | E | the object | — | value not in a closed enumeration |
| `ENUM-OPEN` | W | the object | — | value not in an open enumeration |
| `REF` | E | the attribute | INCOMPLETE | §7.4, §9.5 |
| `CONSTRAINT` | E | the group | INCOMPLETE if it fails because objects are missing | §9.6 |
| `LINK` | E | the link | INCOMPLETE if dangling | §9.8 |
| `RECOMMENDED` | W | the parent | INCOMPLETE | a recommended member is absent |
| `DEPRECATED` | W | the object | — | a deprecated member or value is used |
| `UNITS` | W (Q6) | the dataset | INCOMPLETE if absent | §14 |
| `NAME` | W | the object | — | §4.3 |
| `UNDECLARED` | I, or E with `undeclared: error` | the object | — | §9.7 |
| `NO-DEFINITION` | E with `expect`, else I | the root | INCOMPLETE | §8.8 |
| `UNKNOWN-DEFINITION` | W | the `definition` dataset | — | §8.2 |
| `UNKNOWN-CLASS` | W | the group | — | a class not in the bundle; its children are undeclared (policy of the parent's class) and are not walked further |
| `UNKNOWN-RELEASE` | W | the root | — | §12.3 |
| `SKIPPED` | I | the object | — | a check not done |
| `INCOMPLETE` | I | as the replaced code | — | §11 |
| `BUNDLE` | I | the root | — | the bundle used, when not taken from the file |

**Member of each code.** `MISSING`, `TOO-MANY`, `RECOMMENDED`: the member that is counted. `CLASS`, `NO-CLASS`, `TYPE`, `SHAPE`, `ENUM`, `ENUM-OPEN`, `DEPRECATED`, `UNITS`, `NAME`, `SKIPPED`: the member the object is assigned to, or `null` if it is undeclared (a group without class and without a matching member is reported as `UNDECLARED` and `NO-CLASS`). `SHAPE` for a symbol: `<class>#<symbol>`. `REF`: the attribute's member (role or `names_child`). `CONSTRAINT`: §9.6. `LINK`: the link member. `NO-DEFINITION`: the expected application definition's name, or `null` without `expect`. `UNKNOWN-DEFINITION`, `UNKNOWN-CLASS`, `UNKNOWN-RELEASE`, `BUNDLE`, `UNDECLARED`: `null`. `INCOMPLETE`: as the replaced finding.

The severity of every code, its exceptions (SHAPE W for scalar against length 1; UNDECLARED E with `undeclared: error`; NO-DEFINITION E with `expect`), its path rule and its partial-mode rule are also data in the index (`codes`); a NIAC decision on Q6 changes the index, never the code names.

## 11. Partial mode

Partial mode is for a file that is still being written. It is chosen by the caller; it is never the default.

- The codes marked in §10.3 are replaced by `INCOMPLETE` (I) under the stated condition, with the same path and member; `message` names the replaced code.
- A dataset "can still grow" when its maximum shape is larger than its current shape (HDF5: chunked with unlimited or larger `maxshape`).
- All other findings keep their severity: everything present must already be correct.
- A validator reading a file that another process writes SHOULD open it as allowed by the storage format (HDF5: SWMR read mode, or after the writer flushed and released its lock). This specification does not define file locking.
- A dataset allocated in full and filled step by step cannot be told from a complete one; fill values are not inspected.

**Stopped scans (Q10, provisional).** A writer marks an entry whose scan was stopped early with the attribute `@status="aborted"` on the entry (to be declared in `NXentry` with `enum: [aborted]`; under HDF5 SWMR the writer adds it after leaving SWMR mode). In such an entry, symbol conflicts are reported as `SHAPE` W instead of E, whatever the storage of the datasets. All other findings, including `MISSING`, keep their severity.

## 12. Storage profiles

A profile says how the tree of §2 is stored in one file format. It is data, in the index (`profiles`). Profile `hdf5`:

| Key | Value |
|---|---|
| `root_class` | `NXroot` |
| `class_attribute` | `NX_class`: a text attribute on every group except the root |
| `units_attribute` | `units` |
| `release_attribute` | `NeXus_release`, on the root |
| `entry_points` | `NXentry`, `NXsubentry` |
| `dispatch_dataset` | `definition` |
| `link_target_attribute` | `target` |
| `placeholder_characters` | letters, digits, `_` and `.` (Q3, provisional) |
| `stopped_attribute`, `stopped_value` | `status`, `aborted` (§11; Q10, provisional) |
| `storage` | §13.1 |

### 12.1 Links in HDF5

- Soft and external links are links.
- A hard link: an object with several paths whose `target` attribute names one of its paths; every other path is a link to it. Without such an attribute, all paths are ordinary objects (Q8, provisional).
- External links are resolved by the HDF5 library (`HDF5_EXT_PREFIX`, then relative to the file). A target file that cannot be opened: see §9.8.
- A virtual dataset is a dataset.

### 12.2 Text

A text value is an HDF5 string, fixed or variable length, ASCII or UTF-8. An array of such strings is an array of text values; its storage type is accepted for `NX_CHAR`. Where one text value is needed (`definition`, comparisons with a scalar enumeration value), a one-element array counts as one value. Trailing NUL characters of fixed-length strings are removed before comparison. Leading and trailing white space is significant.

### 12.3 Releases

Bundles are published with a catalogue, `nxds-index.json`, listing every release (`vYYYY.MM`, zero-padded, so that text order is time order), revision and status (`current`, `superseded`, `withdrawn`). A validator SHOULD select the bundle by the root's `NeXus_release` (prefix `v` optional; a suffix after `.post` is ignored): the latest revision of that release that is not withdrawn. If the attribute is absent, the caller chooses (default: the newest current bundle) and `BUNDLE` is reported. A validator that is given one bundle uses it, and reports `UNKNOWN-RELEASE` when the file names another release.

## 13. Data types

The data types and how they relate are taken from `nxdlTypes.xsd` and listed in the index (`types`): each type has a `base` or `members` (for unions).

### 13.1 Storage types (Q7, provisional)

| Type | HDF5 storage types |
|---|---|
| `NX_FLOAT` | float16, float32, float64 |
| `NX_INT` | int8–int64, uint8–uint64 |
| `NX_UINT` | uint8–uint64 |
| `NX_POSINT` | int8–int64, uint8–uint64, with every value ≥ 1 |
| `NX_BOOLEAN` | the h5py boolean enumeration (int8 with FALSE=0, TRUE=1), int8 or uint8 with values 0 and 1 |
| `NX_CHAR`, `NX_DATE_TIME`, `ISO8601` | text (§12.2) |
| `NX_BINARY` | uint8 |
| `NX_CCOMPLEX`, `NX_PCOMPLEX` | complex64, complex128, or a compound of exactly two float fields of the same size (first: real or modulus) |
| `NX_QUATERNION` | float16, float32, float64, with last dimension 4 |
| a union (`NX_NUMBER`, `NX_CHAR_OR_NUMBER`, `NX_COMPLEX`) | the storage types of its members |
| a type with a `base` and no own entry | the storage types of its base |

### 13.2 Date and time

`NX_DATE_TIME` values follow ISO 8601 as restricted by `xs:dateTime`, with a space accepted instead of `T`, the time-zone optional, and the time-zone offset also accepted without colon (`+0100`).

## 14. Units

- A dataset member with `units` requires the units attribute (§12) on the dataset. Absent: `UNITS`.
- The units category's dimensions are in the index (`units`): a list of alternatives, each a map of base dimensions (`length`, `mass`, `time`, `current`, `temperature`, `amount`, `luminosity`, `angle`) to integer powers.
- **Unit strings** follow the grammar of UDUNITS-2 (products with `*`, `.` or space; quotients with `/`; powers with `^` or digits; SI prefixes) with the unit symbols listed in the index (`unit_symbols`); a whole symbol is matched before a prefix is split off (`h` is hour, `u` is atomic mass unit), and a product needs a separator (`um` is micrometre, not `u*m`). An empty string is accepted for the categories marked `empty: true` in the index (`NX_COUNT`, `NX_UNITLESS`, `NX_DIMENSIONLESS`).
- Checking that a unit string parses and has one of the category's dimensions is a capability (`units`); a validator without it reports `SKIPPED`. `NX_ANY` accepts any string, including the empty one.
- `{fixed: "u"}`: the unit string MUST equal `u` after syntactic normalisation (spaces, `.` vs `*`, `^`); `mm` and `0.001 m` are different strings.

## 15. Conformance

The suite in `nxds/conformance/` contains, for every case, everything needed to run it without the reference implementation:

- **Resolution cases:** source classes, and the expected resolved files. Comparison: the keys of §6.2 and the member order; `docs`, `via`, `source` and `provisional` are excluded.
- **Validation cases:** a prebuilt bundle (index and resolved files; cases MAY share one bundle directory), the HDF5 file (and the script that wrote it), options (`expect`, `partial`), required capabilities (`tier-F`, `units`, `partial`, features), and the expected findings. Comparison: the set of `(code, severity, path, member)` for E and W, and in partial mode also for `INCOMPLETE`.

The expected files are the reference: an independent resolver or validator is compared against them, never against the output of `nxds_tools` (the suite's own check that its bundle is current is a maintenance check, not part of conformance). A validator conforms to 0.1 if it gives the expected result for every validation case within the capabilities it declares, using the shipped bundle; a resolver conforms if it gives the expected result for every resolution case. Tiers M and S and the core features (§6.4) are required.

## 16. Translation from NXDL

The meaning of an NXDL class is the meaning of the NXDS class produced by the translation rows T0–T19 (`nxds/generated/translation.md`). The rows only translate; the meaning of the result is defined by this specification. Precedence, explicitly:

- T0 (XSD defaults) applies to an XML attribute that is not written, **except**: `attribute/@optional` (replaced by T4–T6), `field/@maxOccurs` and `group/@maxOccurs` (replaced by T7), `field/@type` and `attribute/@type` (replaced by `defaults.type` and inheritance, §3.1).
- T2: an unnamed group has the label of its class without `NX`, in upper case; a group with a name has that name as label.
- T11 (`choice`): one group member per alternative, all with the same exact name and different classes; matching then selects by class (§7.2).
- Enumeration items keep their text in the translation; they are typed during resolution (§5.2.7).
- T13: the rules of `NXdata` and `NXobject` written in the manual become roles and `names_child` (Q12, provisional). `NXdata/@axes` keeps the non-binding shape of the base class, so its length is checked only through its enumeration, not against the rank of the signal (Q5, Q12).
- T18: a fixed name in a subclass that fits an inherited `template` or `any` member of the same node becomes a member with `refines` (§5.2). This applies to NXDL sources only; NXDS sources write `refines` explicitly.
- An NXDL item without `nameType` has an exact name (T0, XSD default `specified`), also when its name is in upper case (T3b, with a warning).
