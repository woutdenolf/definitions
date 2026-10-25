import json

from nxds_tools._build import build
from nxds_tools._build import write_legacy_tree
from nxds_tools._build import write_outputs
from nxds_tools.bundle import BundleReader
from nxds_tools.model import MemberRef
from nxds_tools.model import ResolvedDocument

from .test_validate import _write
from .test_validate import validate


def test_members_by_reference(demo_build):
    compact = demo_build.resolver.compact(demo_build.documents["NXdemo_x"])
    spec = compact.specialisations["NXdemo_x/ENTRY"]
    refs = {m.ref for m in spec.children if isinstance(m, MemberRef)}
    assert "NXentry/start_time" in refs
    assert "NXobject/DATA" not in refs  # refined: DATA is listed in full
    full = {m.id for m in spec.children if not isinstance(m, MemberRef)}
    assert {"definition", "title", "INSTRUMENT", "DATA"} <= full


def test_reader_lists_every_member_in_full(demo_build):
    reader = demo_build.reader()
    for spec_id, spec in demo_build.documents["NXdemo_x"].specialisations.items():
        group = reader.group(spec_id)
        assert group.children == spec.children
        assert group.attributes == spec.attributes
    assert (
        reader.group("NXslit").children
        == demo_build.documents["NXslit"].definition.children
    )


def test_documentation_is_separate(demo_build):
    reader = demo_build.reader()
    title = next(m for m in reader.group("NXdemo_x/ENTRY").children if m.id == "title")
    assert title.docs == ["NXentry/title"]
    assert reader.doc(title.docs[-1])
    assert reader.doc("NXdemo_x") == "Demo: absorption against energy."
    counter = reader.group("NXdemo_x/ENTRY/INSTRUMENT/counter")
    mode = next(m for m in counter.children if m.id == "mode")
    assert reader.doc(mode.docs[0]) == "Counting mode."
    data = demo_build.bundle().model_dump(mode="json", exclude_none=True)
    text = json.dumps(data["documents"]["NXentry"])
    assert '"doc"' not in text and "Official NeXus NXDL schema" not in text


def test_lazy_directory_and_zip(definitions, demo_dir, tmp_path):
    result = build(definitions, [demo_dir], round_trip=False)
    out = tmp_path / "generated"
    write_outputs(result, out, bundle=tmp_path / "bundle.zip", docs=out / "docs")
    for name in ("NXdemo_x", "NXentry"):
        ResolvedDocument.model_validate_json(
            (out / "resolved" / f"{name}.json").read_text()
        )
    data = _write(tmp_path / "f.h5", title=False, signal=False)
    for source in (out, tmp_path / "bundle.zip"):
        reader = BundleReader.open(source)
        findings = validate(data, reader)
        codes = {(f.code, f.member) for f in findings if f.severity in "EW"}
        assert codes == {
            ("MISSING", "NXdemo_x/ENTRY/DATA@signal"),
            ("RECOMMENDED", "NXdemo_x/ENTRY/title"),
        }
        assert len(reader.loaded()) < 20 < len(reader.index.classes)
    assert BundleReader.open(out).doc("NXentry/title")


def test_phase_2_rejects_lossy(definitions, demo_dir):
    result = build(definitions, [demo_dir], phase=2)
    assert {p.code for p in result.report.errors} == {"lossy"}
    assert all("NXdemo_z" in p.file for p in result.report.errors)


def test_legacy_tree(demo_build, definitions, tmp_path):
    generated = write_legacy_tree(demo_build, definitions, tmp_path / "nxdl")
    assert {"NXslit", "NXmonopd"} <= set(generated)
    assert "NXdemo_y" not in generated  # extra classes are not part of the tree
    assert (tmp_path / "nxdl" / "base_classes" / "NXslit.nxdl.xml").is_file()
    assert (tmp_path / "nxdl" / "base_classes" / "NXentry.nxdl.xml").is_symlink()
    assert (tmp_path / "nxdl" / "nxdl.xsd").exists()
