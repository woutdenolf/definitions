"""The implementation follows the hand-written metaschema (``nxds/metaschema``)."""

import json

import pytest
import yaml

from nxds_tools._build import write_outputs
from nxds_tools.model import Catalogue
from nxds_tools.model import Finding
from nxds_tools.model import Index
from nxds_tools.model import ResolvedDocument
from nxds_tools.model import SourceClass
from nxds_tools.validate import finding_json
from nxds_tools.validate import validate

from ._jsonschema import errors
from .test_validate import _write

_SCHEMAS = ("source", "resolved", "index", "finding", "catalogue")


@pytest.fixture(scope="module")
def schemas(definitions) -> dict[str, dict]:
    folder = definitions / "nxds" / "metaschema"
    return {
        name: json.loads((folder / f"{name}.json").read_text()) for name in _SCHEMAS
    }


def test_metaschema_files(schemas):
    for name, schema in schemas.items():
        assert schema["$id"] == f"{name}.json"
        assert schema["$schema"].endswith("2020-12/schema")


def _check_generated(out, schemas):
    index = json.loads((out / "index.json").read_text())
    assert errors(schemas["index"], index) == []
    Index.model_validate(index)
    resolved = sorted((out / "resolved").glob("*.json"))
    assert resolved
    for path in resolved:
        data = json.loads(path.read_text())
        assert errors(schemas["resolved"], data) == [], path.name
        ResolvedDocument.model_validate(data)
    for path in sorted((out / "source").rglob("*.nxds.yaml")):
        data = yaml.safe_load(path.read_text())
        assert errors(schemas["source"], data) == [], path.name
        SourceClass.model_validate(data)


def test_generated_files_follow_the_metaschema(demo_build, tmp_path, schemas):
    out = tmp_path / "generated"
    write_outputs(demo_build, out)
    _check_generated(out, schemas)


def test_committed_files_follow_the_metaschema(definitions, schemas):
    out = definitions / "nxds" / "generated"
    if (out / "index.json").exists():
        _check_generated(out, schemas)


def test_class_files_follow_the_metaschema(definitions, schemas):
    folders = [definitions / d for d in ("base_classes", "applications")]
    folders.append(definitions / "nxds" / "conformance")
    for folder in folders:
        for path in sorted(folder.rglob("*.nxds.yaml")):
            data = yaml.safe_load(path.read_text())
            assert errors(schemas["source"], data) == [], path
            SourceClass.model_validate(data)


def test_findings_follow_the_metaschema(tmp_path, demo_bundle, schemas):
    path = _write(tmp_path / "f.h5", signal=False, title=False)
    for finding in validate(path, demo_bundle):
        data = json.loads(finding_json(finding))
        assert errors(schemas["finding"], data) == []
        assert Finding.model_validate(data) == finding


def test_catalogue(schemas):
    data = {
        "nxds": "0.1",
        "bundles": [
            {"release": "v2026.01", "revision": 1, "status": "superseded", "path": "a"},
            {"release": "v2026.01", "revision": 2, "status": "current", "path": "b"},
        ],
    }
    assert errors(schemas["catalogue"], data) == []
    Catalogue.model_validate(data)
    data["bundles"][0]["status"] = "old"
    assert errors(schemas["catalogue"], data)


def test_references_are_never_chained(demo_build):
    """Every reference names a member written in full (§6.3)."""
    reader = demo_build.reader()
    for name, document in demo_build.documents.items():
        reader.group(name)
        for spec_id in document.specialisations:
            reader.group(spec_id)
