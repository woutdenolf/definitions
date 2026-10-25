# nxds_tools

Prototype tools for **NXDS**, the NeXus Definition Schema. The specification
is `nxds/spec/nxds.md`; section numbers (§) below and in the code refer to it.
An independent Python project that lives in the definitions repository.

| Module | What it does |
|---|---|
| `nxds_tools.model` | pydantic models of the source form, the resolved form, the index, findings and the catalogue; they follow the hand-written metaschema (`nxds/metaschema`) |
| `nxds_tools.translation` | the NXDL → NXDS translation rows T0–T19 as data |
| `nxds_tools.nxdl` | the compiler: `*.nxdl.xml` → source form, row by row, defaults read from the `nxdl.xsd` being compiled |
| `nxds_tools.source` | read and write `*.nxds.yaml` |
| `nxds_tools.resolve` | source forms → resolved classes, specialisations and the index (§5, §6) |
| `nxds_tools.to_nxdl` | NXDS → NXDL (legacy artifact) and the round-trip check |
| `nxds_tools.bundle` | lazy reader of a bundle (directory, zip or JSON): a class is loaded when used, references are followed |
| `nxds_tools.validate` | lazy HDF5 validator driven by the bundle (§7–§12; tiers M and S, partial mode); findings are yielded as they are found |
| `nxds_tools.docs` | reStructuredText per class, rendered from the bundle |

Requires Python ≥ 3.10, `lxml`, `pyyaml`, `pydantic` 2, `xmlschema`, `h5py`,
`numpy` (and `pytest`, `sphinx` for tests and HTML docs).

## Run

Install once from the root of the definitions repository (`make install` does this, editable):

```bash
pip install -e ./nxds_tools
```

Then, from the root of the repository:

```bash
python -m nxds_tools build --definitions . --out nxds/generated      # = make nxds
python -m nxds_tools check --definitions .                           # exit 1 on errors
python -m nxds_tools build --definitions . --out /tmp/nxds --bundle /tmp/nxds-v2026.01-r1.zip --docs /tmp/nxds/docs
python -m nxds_tools validate data.h5 --bundle nxds/generated [--expect NXmx] [--partial] [--all]
python -m nxds_tools validate data.h5 --bundle /tmp/nxds-v2026.01-r1.zip    # one file, also read lazily
python -m nxds_tools legacy --definitions . --out build/nxdl                 # = make nxds-legacy
python -m nxds_tools docs --definitions . --out build/nxds-docs/source   # make nxds-docs adds sphinx HTML
python -m nxds_tools validate data.h5 --bundle DIR                    # DIR/nxds-index.json: the bundle of the file's release
python -m nxds_tools schema /tmp/schemas                             # JSON Schemas of the models, to compare with nxds/metaschema
python -m nxds_tools translation-table
python -m nxds_tools to-nxdl applications/NXmonopd.nxds.yaml --definitions .
```

`--extra DIR` (repeatable) adds class directories, resolved against the
repository's classes (local classes, the examples in `wip/examples`);
`--only-extra` writes only their outputs; `--legacy DIR` writes the generated
NXDL of NXDS classes; `--phase 2` makes features NXDL cannot express (lossy)
and NXDS versions of `NXdata`/`NXobject` errors; `--bundle X.zip` writes a
lazily readable bundle (index, resolved, docs), `--bundle X.json` one JSON.

`build` writes:

- `source/<dir>/<NXclass>.nxds.yaml`: translated source form of each NXDL class;
- `resolved/<NXclass>.json`: resolved class and its specialisations, one member
  per line, unchanged members as references, no documentation text;
- `index.json`: everything else a validator needs (types, units and unit
  symbols, name rules, the storage profile with the storage types of every
  data type, codes with severity, path and partial-mode rule, decisions,
  statuses), and the class list;
- `translation.md`;
- `report.txt`: every problem with file and line, never an exception.

The metaschema, `nxds/metaschema/{source,resolved,index,finding,catalogue}.json`,
is written by hand (spec §1); the tests check generated files, class files and
findings against it with a small JSON Schema checker, and parse them with the
models.

`validate` prints each finding as soon as it is known (`--json`: one JSON object
per line, §10.1). It opens the file in SWMR mode when possible, walks one group
at a time and every object once at its own path (§9.8: only objects with more
than one hard link get their other paths looked up), keeps assignments only for
objects a link check waits for, and reports a read error as `SKIPPED` instead of
stopping (§9.10).

Classes are read from `base_classes/`, `applications/` and
`contributed_definitions/` only (`*.nxdl.xml` and `*.nxds.yaml`; a class with
both is an error).

## Test

```bash
python -m pytest nxds_tools/tests
```

The tests use the definitions repository around this project
(`NXDS_DEFINITIONS` to use another one) and write their demo classes and HDF5
files to temporary directories. The conformance suite (§15) runs with

```bash
python nxds/conformance/run.py
```
