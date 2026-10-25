import json

from nxds_tools._build import build
from nxds_tools._build import document_json
from nxds_tools.model import ExactName
from nxds_tools.model import RefName
from nxds_tools.model import ResolvedDocument

_IGNORED = {"via", "provisional", "source"}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _IGNORED}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _spec(build_result, spec_id):
    name = spec_id.split("/")[0]
    return build_result.documents[name].specialisations[spec_id]


def _member(group, member_id, node=None):
    return next(
        m
        for m in group.children
        if m.id == member_id and (node is None or m.node == node)
    )


def test_corpus_resolves_without_errors(demo_build):
    assert not demo_build.report.errors, [p.format() for p in demo_build.report.errors]
    assert len(demo_build.documents) >= 280


def test_nxdl_and_nxds_resolve_alike(demo_build):
    """Resolution fixture: the NXDL demo (phase 0) and the NXDS demo (phase 2) mean the same."""
    x = demo_build.documents["NXdemo_x"].model_dump(
        by_alias=True, exclude_none=True, mode="json"
    )
    y = demo_build.documents["NXdemo_y"].model_dump(
        by_alias=True, exclude_none=True, mode="json"
    )
    x_text = (
        json.dumps(_strip(x), sort_keys=True)
        .replace("NXdemo_x", "NXdemo_y")
        .replace("NXdemo_counter_x", "NXdemo_counter_y")
    )
    assert x_text == json.dumps(_strip(y), sort_keys=True)


def test_defaults(demo_build):
    root = demo_build.documents["NXdemo_x"].definition
    entry = _member(root, "ENTRY")
    assert entry.occurs.min == 1 and entry.occurs.max == "unbounded"
    spec = _spec(demo_build, "NXdemo_x/ENTRY")
    title = _member(spec, "title")
    assert title.occurs.min == 0 and title.recommended
    assert title.declared_by == "NXentry" and title.refined_by == ["NXdemo_x"]
    data = _spec(demo_build, "NXdemo_x/ENTRY/DATA")
    signal = next(a for a in data.attributes if a.id == "signal")
    assert (
        signal.occurs.min == 1 and signal.type == "NX_CHAR"
    )  # T5 (Q2), type inherited
    mu = _member(data, "mu")
    assert mu.shape.binding and mu.shape.dims == ["nE"]


def test_name_fit_refinement(demo_build):
    counter = _spec(demo_build, "NXdemo_x/ENTRY/INSTRUMENT/counter")
    i0 = _member(counter, "i0_counts")
    assert i0.refines == "CHANNEL_counts"
    assert i0.type == "NX_INT" and i0.units.category == "NX_COUNT"
    assert i0.name == ExactName(exact="i0_counts")
    assert i0.occurs.max == 1  # §3.1: an exact name with refines
    assert _member(counter, "CHANNEL_counts").occurs.min == 0  # the template stays
    instrument = _spec(demo_build, "NXdemo_x/ENTRY/INSTRUMENT")
    assert _member(instrument, "monochromator").refines == "MONOCHROMATOR"


def test_roles_and_shared_ids(demo_build):
    data = _spec(demo_build, "NXdemo_x/ENTRY/DATA")
    role = _member(data, "DATA", "dataset")
    assert role.name == RefName(ref="@signal")
    assert _member(data, "DATA", "group").node == "group"  # Q11: same id, other kind


def test_link_target(demo_build):
    data = _spec(demo_build, "NXdemo_x/ENTRY/DATA")
    assert _member(data, "energy").target == "ENTRY/INSTRUMENT/monochromator/energy"
    root = demo_build.documents["NXdemo_x"].definition
    assert (
        demo_build.resolver.resolve_target(
            root, "ENTRY/INSTRUMENT/monochromator/energy"
        ).node
        == "dataset"
    )


def test_round_trip_and_lossy(demo_build):
    assert demo_build.lossy["NXdemo_y"] == []
    assert demo_build.lossy["NXdemo_z"] == ["require"]
    assert demo_build.documents["NXdemo_z"].definition.lossy == ["require"]
    assert not [
        p
        for p in demo_build.report.problems
        if p.code == "round-trip" and p.severity == "error"
    ]


def test_document_json_is_valid_and_deterministic(demo_build):
    text = document_json(demo_build.documents["NXdemo_x"])
    assert text == document_json(demo_build.documents["NXdemo_x"])
    ResolvedDocument.model_validate_json(text)


def test_problems_are_reported_not_raised(definitions, tmp_path):
    extra = tmp_path / "bad"
    extra.mkdir()
    (extra / "NXbad_a.nxds.yaml").write_text(
        "nxds: '0.1'\nclass: NXbad_a\ncategory: base\nextends: NXnothing\ndefaults: {min: 0, binding: false}\n"
    )
    (extra / "NXbad_b.nxds.yaml").write_text("class: NXbad_b\ncategory: base\n")
    (extra / "NXslit.nxds.yaml").write_text("class: NXslit\n")
    (extra / "NXbad_c.nxds.yaml").write_text(
        "class: NXbad_c\ncategory: base\nextends: NXobject\ndefaults: {min: 0, binding: false}\n"
        "children:\n  x: {node: dataset}\n  g: {node: group, class: NXmissing}\n"
    )
    result = build(definitions, [extra], round_trip=False)
    codes = {p.code for p in result.report.errors}
    assert {
        "unknown-extends",
        "missing-defaults",
        "duplicate-class",
        "unknown-class",
    } <= codes


def test_widening_and_narrowing_warnings(definitions, tmp_path):
    extra = tmp_path / "warn"
    extra.mkdir()
    (extra / "NXwarn_a.nxds.yaml").write_text(
        "class: NXwarn_a\ncategory: application\ndescribes: NXroot\ndefaults: {min: 1, binding: true}\n"
        "children:\n  ENTRY:\n    node: group\n    class: NXentry\n    name: {any: true}\n"
        "    occurs: {min: 0}\n    children:\n      duration: {node: dataset, type: NX_CHAR}\n"
    )
    result = build(definitions, [extra], round_trip=False)
    codes = {
        p.code for p in result.report.problems if p.file.endswith("NXwarn_a.nxds.yaml")
    }
    assert {"widened-occurs", "type-not-narrower"} <= codes


def test_enumerations_typed_after_resolution(demo_build):
    """§5.2.7: NXDL item values take the resolved type and shape."""
    efficiency = demo_build.documents["NXdetector"].specialisations[
        "NXdetector/efficiency"
    ]
    reader = demo_build.reader()
    spec = reader.group(efficiency.id)
    values = {
        a.id: [v.value for v in a.enum.values]
        for m in spec.children
        for a in [m, *getattr(m, "attributes", [])]
        if a.enum is not None
    }
    values.update(
        {a.id: [v.value for v in a.enum.values] for a in spec.attributes if a.enum}
    )
    assert values.get("wavelength_indices") == [0]
    assert values["axes"][:2] == [".", [".", "."]]
