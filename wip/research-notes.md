# Research notes for the NXDS proposal

Collected by LLM research agents from the definitions repository (main, all
open issues and pull requests as of 2026-10-03), the NeXus wiki, the validator
libraries and `nexusformat_pydantic`. Wiki pages are published at
`https://www.nexusformat.org/<Page>.html`; issues and pull requests at
`https://github.com/nexusformat/definitions/issues/<n>`.

## 1. Wiki: needs and pain points (2024–2026)

- NIAC2026 open discussion "what is a blocker with NeXus": "NXDL is a blocker;
  NYAML helps, but still uncomfortable unconventional rules e.g. PARTIAL names";
  "how to extend the schema?"; "semantic definition being independent from actual
  binary representation?" — [NIAC2026_minutes](https://www.nexusformat.org/NIAC2026_minutes.html) L138–146.
- YM (RWTH): "cnxvalidate does not recognise partial names; NeXpy also shows error
  regarding the incorrect use of symbols" — NIAC2026_minutes L167–169.
- RO: "cnxvalidate is there but not developed any longer" — NIAC2026_minutes L276.
- BW: "single source of truth in NeXus is the definition in NXDL. It shall not be
  the validator which provides the truth … Tech manager shall be responsible for the
  validation tool and we also need one for managing NXDL" — NIAC2026_minutes L277.
- EL (HZB, Bluesky): "mapping to App defs (pydantic model from NXDL)" — NIAC2026_minutes L80.
- WdN: "move away from XML and use pydantic" — NIAC2026_minutes L258.
- AB: "cleaner and simplified documentation"; examples for each application
  definition; "github action for checking definitions (and definitions changes)
  against known example data files" — NIAC2026_minutes L259, L264–271.
- PM: "looking for a library that exposes base class as python types" — [Telco_20240311](https://www.nexusformat.org/Telco_20240311.html) L51.
- PJ: "a validator cannot understand this. What we need is a way to express this
  properly in NXDL" — [NIAC2022_spring_minutes](https://www.nexusformat.org/NIAC2022_spring_minutes.html) L42.
- AB: "we have not fully defined the expected behavior of validators" — [Telco_20251020](https://www.nexusformat.org/Telco_20251020.html) L62.
- NXcollection validation disputed — [Telco_20250430](https://www.nexusformat.org/Telco_20250430.html) L59–72, [Telco_20260610](https://www.nexusformat.org/Telco_20260610.html) L48–49.
- Inherited members not rendered: HB "better to provide a flat and complete
  documentation" — [Telco_20250127](https://www.nexusformat.org/Telco_20250127.html) L68–73; WdN "if we could render inherited
  optional elements, that would solve quite some resistance towards restructuring" — [Telco_20250916](https://www.nexusformat.org/Telco_20250916.html) L66.
- Versioning: AB "Versioning has been discussed, but we do not have them in NeXus" — [Telco_20260826](https://www.nexusformat.org/Telco_20260826.html) L59–62.
- AB: NeXus is "1) self-descriptive machine-readable standard? 2) community
  agreement?" — [Telco_20251118](https://www.nexusformat.org/Telco_20251118.html) L52–53.
- Storage-format independence: NIAC2012 guiding statement "NeXus can be mapped to
  different physical file formats" — [NIAC2012](https://www.nexusformat.org/NIAC2012.html) L437–443; AB "NeXus is meant to be
  independent of the file format implementation" — [Telco_20220225](https://www.nexusformat.org/Telco_20220225.html) L67; LG "NeXus is a
  data format and not a file format" — [Telco_20230920](https://www.nexusformat.org/Telco_20230920.html) L49; BW "the current method of
  describing it in the manual is informal and quickly becomes unmanageable when
  adding further file formats" — [Telco_20220426](https://www.nexusformat.org/Telco_20220426.html) L66.
- Precedent: in 2007 the NIAC voted that "Version 3.0 will be schema based" and that
  "canonical NeXus definitions [are] to be stored in schema" — [NIAC2007_Minutes](https://www.nexusformat.org/NIAC2007_Minutes.html) L214–230.

## 2. Wiki: governance

- Officers: Chair, Executive Secretary, Technical Manager, Definition Release
  Manager — [NIAC](https://www.nexusformat.org/NIAC.html) L98–151. Full meetings are biennial (NOBUGS years), code
  camps in between; telcos monthly.
- Votes: simple majority at meetings; outside meetings ≥ 2/3 of members respond
  within two weeks (13 of 20 votes in 2026); GitHub emoji votes.
- No vote needed for documentation-only changes, bug fixes, technical changes that
  do not change NeXus and its definitions, additions to contributed definitions.
- Technical Manager: unfilled since 2024; NIAC2026 discussed giving it the
  validator and a separate NXDL role; no election recorded.
- WdN: NIAC member (ESRF, term to May 2028); contributed-definitions subcommittee;
  NXdata review subcommittee; NXdata @axes rewrite (#1396).

## 3. Likely objections (to address respectfully)

- "NXDL is our contract; it must stay the single source of truth" (AB, [Telco_20231019](https://www.nexusformat.org/Telco_20231019.html) L49; BW NIAC2026).
- Scope: no Python packaging in the definitions repository (Telco_20231019 L47–48).
- "Not the core mission"; "we should focus on the definitions" (BW, Telco_20260610 L36).
- Resources are voluntary (BW, [Telco_20220824](https://www.nexusformat.org/Telco_20220824.html) L55).
- "Do not make NeXus even more complex" (HB, Telco_20250430 L56).
- Stability: "The standard is stable for long years" (AB, [Telco_20241106](https://www.nexusformat.org/Telco_20241106.html) L69).
- Voting load and quorum.

## 4. Open pull requests that matter

- #1650 (WdN): reuse of inherited documentation (`reused_concepts`, `reused_from`),
  symbol checks, `make docdiff`. Implements part of phase 0/1 already; NXDS must
  build on it. Conflicts with #1664 (symbols in NXsample).
- #1669 (WdN, draft): `fieldAttributes`, `valueFrom="class"`, links by content
  ("a copy is a link"). Flips the link default (D8) if merged; `NX_class` must map to
  the storage profile, not a member.
- #1533 (FAIRmat): `field/@extends` names the refined member (AXISNAME or DATA).
- #1558, #1570: generic `FIELDNAME` member in NXobject (superseded by #1669 semantics).
- #1664, #1676: symbol clean-up in base classes (D5).
- #1645: dormant contributions directory → class `status`.
- #1509: CONTRIBUTING.md — place for the new rules.
- #937: `definition/@revision`.
- #1033: NXdata transformation role (T13 does not scale; roles should be declarable).
- #1286: NXsubentry overlay with group links.
- #1631: deprecating an enumeration value (per-value `deprecated`).
- Class-content PRs: #1640/#1651 (XAS — do not use NXxas as example), #1632, #1646,
  #1648, #1653, #1655 (promotions), #1561 (two `any` fields told apart only by units),
  #1574 (unit category with two dimensions), #1610 (default value in prose).

## 5. Corpus facts that the design must handle

- Same name for a dataset and a group: NXsample `magnetic_field`; NXdata `DATA`
  (dataset) vs `DATA` (NXdata group from NXobject).
- Enumerations replaced, not narrowed: NXarpes `acquisition_mode`; `definition` in
  application definitions that extend another one (NXxbase→NXxrot, NXmpes→NXmpes_arpes).
- Name-fit refinement used by today's tools and docs (`nxdl_utils`).
- Dimension expressions (`tof+1`, `2n`, sums), symbolic and undeclared ranks
  (`dataRank`, `anyRank`), optional dimensions (`required="false"`).
- Upper-case names without `nameType` (#1490).
- Unit categories with several dimensions.

## 6. Open issues that need a question for the NIAC

- Several application definitions per entry (#1443).
- NXdata rules (#598, #1214, #1383, #1388, #1555).
- Reserved prefixes/suffixes (#1492, #1595, #1013).
- Dataset or NXlog under one name (#1440, #1571).
- Enumeration wildcards and numeric enumerations (#1234, #1235); reusable enumerations (#1379).
- Arithmetic in dimensions (#1084).
- Common base of NXroot and NXobject (#1672, #1494).
