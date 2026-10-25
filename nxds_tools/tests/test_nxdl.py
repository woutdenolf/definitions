from pathlib import Path

from nxds_tools._report import Report
from nxds_tools.model import AnyName
from nxds_tools.model import AtMostOneOf
from nxds_tools.model import DimExpr
from nxds_tools.model import OptionalDim
from nxds_tools.model import RefName
from nxds_tools.model import TemplateName
from nxds_tools.nxdl import compile_file
from nxds_tools.nxdl import target_to_ids
from nxds_tools.nxdl import typed_enum

_NS = 'xmlns="http://definition.nexusformat.org/nxdl/3.1"'


def _compile(
    tmp_path: Path, facts, name: str, category: str, body: str, extra: str = ""
):
    path = tmp_path / f"{name}.nxdl.xml"
    path.write_text(
        f'<definition name="{name}" type="group" category="{category}" {extra} {_NS}>{body}</definition>'
    )
    report = Report()
    compiled = compile_file(path, path.name, facts, report)
    return compiled, report


def test_t2_unnamed_group(tmp_path, facts):
    compiled, _ = _compile(tmp_path, facts, "NXa", "base", '<group type="NXdata"/>')
    member = compiled.source.children["DATA"]
    assert isinstance(member.name, AnyName)
    assert "T2" in member.via


def test_t3_partial_and_t3b(tmp_path, facts):
    body = '<field name="AXISNAME_indices" nameType="partial"/><field name="Q"/>'
    compiled, report = _compile(tmp_path, facts, "NXa", "base", body)
    assert compiled.source.children["AXISNAME_indices"].name == TemplateName(
        template="{AXISNAME}_indices"
    )
    assert compiled.source.children["Q"].name is None  # exact, the id
    assert any(p.code == "upper-case-exact" for p in report.problems)


def test_t4_t5_t6_occurrence(tmp_path, facts):
    body = (
        '<group type="NXentry"><field name="a"/><field name="b" optional="true"/>'
        '<field name="c" recommended="true"/><field name="d" minOccurs="2" optional="true"/>'
        '<attribute name="e"/></group>'
    )
    compiled, report = _compile(tmp_path, facts, "NXapp", "application", body)
    assert compiled.source.defaults.min == 1
    children = compiled.source.children["ENTRY"].children
    assert children["a"].occurs is None and "T5" in children["a"].via
    assert children["b"].occurs.min == 0
    assert children["c"].occurs.min == 0 and children["c"].recommended
    assert children["d"].occurs.min == 2  # minOccurs wins over optional
    assert any(p.code == "conflicting-occurrence" for p in report.problems)
    assert (
        compiled.source.children["ENTRY"].attributes["e"].occurs is None
    )  # T5 overrides the XSD default


def test_t8_extends(tmp_path, facts):
    base, _ = _compile(tmp_path, facts, "NXb", "base", "")
    assert base.source.extends == "NXobject"
    app, _ = _compile(tmp_path, facts, "NXapp", "application", "", 'extends="NXobject"')
    assert app.source.extends is None and app.source.describes == "NXroot"


def test_t9_dimensions(tmp_path, facts):
    body = (
        '<field name="x"><dimensions rank="3"><dim index="1" value="n"/>'
        '<dim index="2" value="tof+1"/><dim index="3" value="4" required="false"/></dimensions></field>'
        '<field name="y"><dimensions rank="dataRank"/></field>'
    )
    compiled, _ = _compile(tmp_path, facts, "NXb", "base", body)
    shape = compiled.source.children["x"].shape
    assert shape.dims == [
        "n",
        DimExpr(expr="tof+1"),
        OptionalDim(optional=True, value=4),
    ]
    assert compiled.source.children["y"].shape.rank == "dataRank"


def test_t10_target():
    assert (
        target_to_ids("/NXentry/NXinstrument/mono:NXmonochromator/energy")
        == "ENTRY/INSTRUMENT/mono/energy"
    )


def test_t11_choice(tmp_path, facts):
    body = '<choice name="shape"><group type="NXoff_geometry"/><group type="NXcylindrical_geometry"/></choice>'
    compiled, _ = _compile(tmp_path, facts, "NXb", "base", body)
    assert set(compiled.source.children) == {
        "shape_OFF_GEOMETRY",
        "shape_CYLINDRICAL_GEOMETRY",
    }
    assert compiled.source.require == [
        AtMostOneOf(at_most_one_of=["shape_OFF_GEOMETRY", "shape_CYLINDRICAL_GEOMETRY"])
    ]


def test_t12_ignore_extra(tmp_path, facts):
    compiled, _ = _compile(
        tmp_path, facts, "NXb", "base", "", 'ignoreExtraFields="true"'
    )
    assert compiled.source.undeclared.dataset == "ignore"
    assert compiled.source.undeclared.group == "report"


def test_t13_roles(tmp_path, facts):
    body = '<attribute name="auxiliary_signals"/><field name="DATA" nameType="any"/><field name="AXISNAME" nameType="any"/>'
    compiled, _ = _compile(tmp_path, facts, "NXdata", "base", body)
    assert compiled.source.children["DATA"].name == RefName(ref="@signal")
    assert compiled.source.children["AXISNAME"].name == RefName(ref="@axes")
    assert compiled.source.attributes["auxiliary_signals"].names_child == "dataset"


def test_enumeration_typed(tmp_path, facts):
    body = '<field name="n" type="NX_INT"><enumeration><item value="1"/><item value="2"/></enumeration></field>'
    compiled, _ = _compile(tmp_path, facts, "NXb", "base", body)
    member = compiled.source.children["n"]
    assert [v.value for v in member.enum.values] == ["1", "2"]  # typed later
    enum, bad = typed_enum(member.enum, "NX_INT", None, facts.types)
    assert [v.value for v in enum.values] == [1, 2] and bad == []


def test_t19_legacy_attributes(tmp_path, facts):
    compiled, _ = _compile(
        tmp_path, facts, "NXb", "base", '<field name="d" signal="1"/>'
    )
    attribute = compiled.source.children["d"].attributes["signal"]
    assert attribute.enum.values[0].value == "1" and attribute.occurs.min == 0
    enum, _ = typed_enum(attribute.enum, attribute.type, None, facts.types)
    assert enum.values[0].value == 1


def test_bad_file_is_reported(tmp_path, facts):
    path = tmp_path / "NXbad.nxdl.xml"
    path.write_text("<definition")
    report = Report()
    assert compile_file(path, path.name, facts, report) is None
    assert report.errors


def test_t9b_expressions(tmp_path, facts):
    body = (
        '<field name="x"><dimensions rank="2"><dim index="1" value="2n"/>'
        '<dim index="2" value="n + 1"/></dimensions></field>'
        '<field name="y"><dimensions rank="n+1"/></field>'
    )
    compiled, report = _compile(tmp_path, facts, "NXb", "base", body)
    assert compiled.source.children["x"].shape.dims == [
        DimExpr(expr="2*n"),
        DimExpr(expr="n+1"),
    ]
    assert compiled.source.children["y"].shape.rank == DimExpr(expr="n+1")
    assert not any(p.code == "bad-rank" for p in report.problems)


def test_enumeration_lists(tmp_path, facts):
    body = (
        '<field name="a"><dimensions rank="1"/><enumeration>'
        '<item value=". ."/><item value="x"/></enumeration></field>'
        '<field name="b"><enumeration><item value=". ."/></enumeration></field>'
        '<field name="c" type="NX_INT"><dimensions rank="1"/><enumeration>'
        '<item value="1 2"/></enumeration></field>'
        '<field name="d" axes="x y"/>'
        '<field name="e" type="NX_INT"><dimensions rank="1"/><enumeration>'
        '<item value="[0, 0, 1]"/></enumeration></field>'
    )
    compiled, _ = _compile(tmp_path, facts, "NXb", "base", body)
    children = compiled.source.children

    def typed(member):
        enum, _ = typed_enum(member.enum, member.type, member.shape, facts.types)
        return [v.value for v in enum.values]

    assert typed(children["a"]) == [[".", "."], "x"]
    assert typed(children["b"]) == [". ."]
    assert typed(children["c"]) == ["1 2"]  # only text members split (§5.2.7)
    assert typed(children["e"]) == [[0, 0, 1]]
    assert children["d"].attributes["axes"].enum.values[0].value == ["x", "y"]


def test_t10_base_class_targets_are_absolute(tmp_path, facts):
    body = '<link name="x" target="/NXentry/NXdata/y"/>'
    compiled, _ = _compile(tmp_path, facts, "NXb", "base", body)
    assert compiled.source.children["x"].target == "/ENTRY/DATA/y"
    compiled, _ = _compile(
        tmp_path, facts, "NXapp", "application", f'<group type="NXentry">{body}</group>'
    )
    assert compiled.source.children["ENTRY"].children["x"].target == "ENTRY/DATA/y"
