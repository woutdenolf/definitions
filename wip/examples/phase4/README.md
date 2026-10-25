# Phase 4: the end state

Every class is written in NXDS. The repository then contains:

```
nxds/
  spec/                       the NXDS specification
  metaschema/                 JSON Schemas of class files, resolved files, the index and findings
  conformance/                resolution and validation fixtures
  generated/resolved/*.json   resolved form per class (reviewed in pull requests)
base_classes/*.nxds.yaml
applications/*.nxds.yaml
contributed_definitions/*.nxds.yaml
nxdl.xsd, nxdlTypes.xsd       frozen as "NXDL 3.1 (legacy)", used only for old releases
```

and a release attaches `nxds-<release>-r<revision>.json` (the bundle). Here:
`NXdemo_phase4.nxds.yaml` and `NXdemo_counter_phase4.nxds.yaml` (written by the author)
and `generated/resolved/` (generated). `require:` is an ordinary feature; no
legacy NXDL is generated any more.
