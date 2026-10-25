# NXDS (prototype)

`generated/` is written by `make nxds` (`nxds_tools build`) and must be
committed with every pull request that changes a class; CI fails when it is
out of date (`.github/workflows/nxds.yaml`).

- `generated/source/<dir>/<NXclass>.nxds.yaml`: the NXDS source form translated
  from each NXDL class (`via`: translation rows used; `provisional`: open
  decisions Q1–Q14).
- `generated/resolved/<NXclass>.json`: the resolved form of each class and its
  specialisations, one member per line, so a pull request shows the change of
  meaning as a diff. A member the class does not change is a reference to the
  entry listed in full where it was last changed
  (`{"ref": "NXobject/DATA", "node": "group"}`, `{"ref": "NXobject@default"}`);
  a reader replaces it by that entry, it never merges. Documentation texts are
  not part of the resolved form (`docs` lists their keys); `build --docs DIR`
  writes them, for the documentation build only.
- `generated/index.json`: types, units, name grammar, storage profile, finding
  codes and the list of classes; with `resolved/` it is a bundle a validator
  reads lazily (`nxds_tools validate FILE --bundle nxds/generated`).
- `generated/translation.md`: the translation table.
- `generated/report.txt`: compile and resolution problems, with file and line.

`spec/nxds.md`: the specification. `metaschema/`: JSON Schemas of class files,
resolved files, the index, findings and the bundle catalogue, written by hand;
the tests of `nxds_tools` check the implementation against them. `conformance/`: resolution and validation cases and their
runner (see its README).

`make nxds-legacy` writes `build/nxdl/`: every class as NXDL (repository files
linked, NXDS classes generated). `make test`, `make prepare` and `make nxtest`
point `dev_tools` at it (`NEXUS_DEF_PATH`), so the manual still documents
classes written in NXDS.

Classes written in NXDS live next to the NXDL files as
`<dir>/<NXclass>.nxds.yaml` (here: `base_classes/NXslit.nxds.yaml`,
`applications/NXmonopd.nxds.yaml`); a class has exactly one source.
