# NXDS conformance suite

Cases that pin the meaning of NXDS (spec §15) in a neutral format: class files,
resolved files, bundles, HDF5 files and expected findings as JSON. Every case
contains everything needed to run it without `nxds_tools`; `run.py` runs them
with `nxds_tools` (the reference implementation):

```bash
PYTHONPATH=nxds_tools/src python nxds/conformance/run.py            # all cases
PYTHONPATH=nxds_tools/src python nxds/conformance/run.py --update   # rewrite expected files, bundles, HDF5 files
```

## Layout

```
classes/                     minimal base classes shared by every case (NXDS):
                             NXobject, NXroot, NXentry, NXinstrument, NXmonochromator,
                             NXdata (roles), NXcounter (template, free name), NXsensor
resolution/<case>/
  case.yaml                  description, covers: [rows or features]
  *.nxds.yaml | *.nxdl.xml   the classes under test
  expected/<NXclass>.json    the expected resolved form of every class the case uses
validation/bundle/           the prebuilt bundle all validation cases share: index.json and
                             resolved/<NXclass>.json of classes/ and every resolution case
validation/<case>/
  case.yaml                  description, expect?, partial?,
                             capabilities: [tier-F, units, partial]
  bundle/                    (optional) a bundle of the case's own, used instead
  data.h5                    the file to validate
  make_file.py <path>        the script that wrote it (h5py; helpers in validation/_common.py)
  expected.jsonl             the expected findings, one JSON object per line
```

A case resolves only `classes/` and its own classes (the shared bundle: all
resolution cases), never the classes of the repository, so a case does not
change when a class of the repository does. Every class is core NXDS 0.1, so
`requires` is empty and no case needs a feature capability.

## Rules (spec §15)

- **Resolution:** the resolved form of each class (members by reference, as in
  `nxds/generated/resolved/`) equals `expected/<NXclass>.json`, member order
  included, without the keys `docs`, `via`, `source` and `provisional`.
- **Validation:** validating `data.h5` with `bundle/` (and the options of
  `case.yaml`) gives the set of `(code, severity, path, member)` of
  `expected.jsonl` for the findings with severity E or W, and in partial mode
  also for `INCOMPLETE`. Order, `message` and other I findings do not matter. A
  validator runs a case only if it has the capabilities listed.
- `run.py` also checks that the shared bundle equals the one `nxds_tools`
  builds from the classes, so it never goes stale.

## Cases

| Case | What it pins |
|---|---|
| resolution/defaults | `defaults.min`, `max` from the name kind, binding shapes, recommended, specialisations |
| resolution/name-fit | NXDL only: a fixed name refines the template/free member it fits (T18), placed right after it, keeping its type, units and maximum (§3.1) |
| resolution/refines | NXDS: `refines` written by the author (§5.2), placement and inheritance |
| resolution/choice | `choice` (T11): one exact member per class, `exactly_one_of` |
| resolution/nxdl-translation | an NXDL class: T2, T5, T6, T7, T9, T10 |
| resolution/constraints | `require: at_least_one_of` |
| resolution/symbols | `shape.symbols`, an expression `2*n` |
| resolution/link-refines | a target path through a refining member (§4.6); a link member refining a dataset member (§5.1) |
| resolution/subentry | dispatch members, a subentry restricted to another definition (§8.4) |
| resolution/subclass | a specialised base-class member and a subclass |
| resolution/enum-lists | list-valued and scalar enumeration values (§4.5) |
| resolution/enum-typing | NXDL enumeration values typed with the inherited type and shape (§5.2.7) |
| validation/missing-recommended | MISSING attribute, RECOMMENDED dataset |
| validation/partial | the same file in partial mode: INCOMPLETE |
| validation/partial-link | partial mode with a dangling link and a missing group |
| validation/link-target | LINK to the wrong object (§9.8); the role named by `@signal` (TYPE) |
| validation/role-ref | a role naming a missing child (REF); `.` skipped |
| validation/constraint | CONSTRAINT, with `expect` |
| validation/choice | two exact members told apart by class (§7.2); CLASS fallback (§7.3) |
| validation/dispatch | two entries following different definitions, one unknown (§8) |
| validation/symbols | one SHAPE per symbol and entry (§9.3); stopped entries (`@status="aborted"`, §11): W; a failing expression |
| validation/refines | objects of a member with `refines` count towards the refined member (§9.1) |
| validation/type-enum | TYPE on a name-fit member, ENUM, UNITS |
| validation/link-refines | a link target reached through a refining member (NXtomo-like); a wrong target (LINK) |
| validation/link-member | a dataset where a link member (refining a dataset member) is required |
| validation/subentry | a subentry following another definition: counted for the outer member, checked against its own |
| validation/external | a link into a file that cannot be opened: present, checks SKIPPED, no LINK |
| validation/subclass | leftovers (children and attributes) of a subclass object matched against its own class (§8.7); a link after its target inside it |
| validation/expect | `expect` with no dispatched group: NO-DEFINITION E (the I finding is not reported) |
| validation/role-kind | a role filled by a child of the wrong kind (REF) |
| validation/enum-lists | a list value applies to the whole array, a scalar to each element |
| validation/enum-typing | a numeric enumeration of an NXDL class, compared as the stored type |
| validation/link-after-target | a link after its target in walk order, in a dispatched entry (the target's assignment found again) |
| validation/external-target | a link to an object in another file, walked before the link |

## One case in full: `validation/missing-recommended`

The class under test, `resolution/nxdl-translation/NXcase_nxdl.nxdl.xml`
(NXDL, so the translation rows apply):

```xml
<definition name="NXcase_nxdl" extends="NXobject" type="group" category="application"
            xmlns="http://definition.nexusformat.org/nxdl/3.1">
  <symbols><symbol name="n"><doc>length</doc></symbol></symbols>
  <group type="NXentry">
    <field name="definition"><enumeration><item value="NXcase_nxdl"/></enumeration></field>
    <field name="title" recommended="true"/>
    <field name="start_time" optional="true"/>
    <group type="NXinstrument">
      <group name="monochromator" type="NXmonochromator">
        <field name="energy" type="NX_FLOAT" units="NX_ENERGY">
          <dimensions rank="1"><dim index="1" value="n"/></dimensions>
        </field>
      </group>
    </group>
    <group type="NXdata">
      <attribute name="signal"/>
      <link name="energy" target="/NXentry/NXinstrument/monochromator:NXmonochromator/energy"/>
    </group>
  </group>
</definition>
```

`validation/missing-recommended/case.yaml`:

```yaml
description: A required attribute is missing (MISSING), a recommended dataset is absent (RECOMMENDED).
classes: [../../resolution/nxdl-translation]
capabilities: []
```

`validation/missing-recommended/make_file.py` writes `data.h5` (no `@signal` on
`data`, no `title`):

```
/                     @NX_class=NXroot
  entry               @NX_class=NXentry
    definition        "NXcase_nxdl"
    instrument        @NX_class=NXinstrument
      monochromator   @NX_class=NXmonochromator
        energy        float64[5]  @units="keV"
    data              @NX_class=NXdata
      energy          soft link → /entry/instrument/monochromator/energy
```

`validation/missing-recommended/expected.jsonl`:

```json
{"code": "MISSING", "severity": "E", "path": "/entry/data", "member": "NXcase_nxdl/ENTRY/DATA@signal"}
{"code": "RECOMMENDED", "severity": "W", "path": "/entry", "member": "NXcase_nxdl/ENTRY/title"}
```

Why, from the resolved form (`validation/bundle/resolved/NXcase_nxdl.json`):

- `@signal` is written in an application definition without `optional`, so
  T5 gives `min: 1` (provisional Q2): `MISSING` at the group's path, member
  `<specialisation>@signal`.
- `title` has `recommended="true"`, so T6 gives `min: 0, recommended: true`:
  `RECOMMENDED` at the parent's path.
- `start_time` is `optional="true"`: nothing. The link `energy` points to the
  object assigned to `ENTRY/INSTRUMENT/monochromator/energy` in the same entry:
  nothing.
- The file has no `@NeXus_release`, which gives `BUNDLE` (severity I), not
  compared.

For comparison, two members of `resolution/defaults/expected/NXcase_defaults.json`
(an NXDS class with `defaults: {min: 1, binding: true}`):

```json
{"declared_by": "NXentry", "id": "title", "name": {"exact": "title"}, "node": "dataset", "occurs": {"max": 1, "min": 0}, "recommended": true, "refined_by": ["NXcase_defaults"], "type": "NX_CHAR"},
{"declared_by": "NXcase_defaults", "id": "y", "name": {"exact": "y"}, "node": "dataset", "occurs": {"max": 1, "min": 1}, "recommended": false, "shape": {"binding": true, "dims": ["n"], "symbols": {"n": "NXcase_defaults"}}, "type": "NX_FLOAT"}
```
