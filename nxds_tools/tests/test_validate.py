import json
from collections.abc import Iterator

import h5py
import numpy as np
import pytest

from nxds_tools.model import Finding
from nxds_tools.validate import _evaluate
from nxds_tools.validate import finding_json
from nxds_tools.validate import validate as _validate


def validate(*args, **kwargs):
    return list(_validate(*args, **kwargs))


def _write(
    path,
    *,
    title=True,
    signal=True,
    points=5,
    total=5,
    units=True,
    energy_dtype="f8",
    definition="NXdemo_x",
    soft=True,
):
    with h5py.File(path, "w") as root:
        root.attrs["NX_class"] = "NXroot"
        root.attrs["NeXus_release"] = "v2026.01"
        entry = root.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        if definition:
            entry["definition"] = definition
        if title:
            entry["title"] = "a scan"
        instrument = entry.create_group("instrument")
        instrument.attrs["NX_class"] = "NXinstrument"
        mono = instrument.create_group("monochromator")
        mono.attrs["NX_class"] = "NXmonochromator"
        mono["energy"] = np.linspace(1, 2, total).astype(energy_dtype)
        if units:
            mono["energy"].attrs["units"] = "keV"
        counter = instrument.create_group("counter")
        counter.attrs["NX_class"] = "NXdemo_counter_x"
        counter["mode"] = "timer"
        counter.create_dataset(
            "i0_counts", data=np.arange(points, dtype="i4"), maxshape=(None,)
        )
        counter["i0_counts"].attrs["units"] = ""
        data = entry.create_group("data")
        data.attrs["NX_class"] = "NXdata"
        if signal:
            data.attrs["signal"] = "mu"
        data.create_dataset("mu", data=np.zeros(points), maxshape=(None,))
        if soft:
            data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
    return path


def _codes(findings, severities=("E", "W")):
    return {
        (f.code, f.severity, f.path, f.member)
        for f in findings
        if f.severity in severities
    }


def test_valid_file(tmp_path, demo_bundle):
    findings = validate(_write(tmp_path / "ok.h5"), demo_bundle)
    assert _codes(findings) == set()


def test_proposal_phase1_example(tmp_path, demo_bundle):
    """The findings of the proposal, §5 phase 1."""
    findings = validate(
        _write(tmp_path / "f.h5", title=False, signal=False), demo_bundle
    )
    assert _codes(findings) == {
        ("MISSING", "E", "/entry/data", "NXdemo_x/ENTRY/DATA@signal"),
        ("RECOMMENDED", "W", "/entry", "NXdemo_x/ENTRY/title"),
    }


def test_partial_mode(tmp_path, demo_bundle):
    path = _write(tmp_path / "p.h5", title=False, signal=False, points=3, total=10)
    findings = validate(path, demo_bundle, partial=True)
    assert _codes(findings) == set()
    incomplete = {(f.path, f.member) for f in findings if f.code == "INCOMPLETE"}
    assert incomplete == {
        ("/entry/data", "NXdemo_x/ENTRY/DATA@signal"),
        ("/entry", "NXdemo_x/ENTRY/title"),
        ("/entry", "NXdemo_x#nE"),
    }
    findings = validate(path, demo_bundle)
    assert ("SHAPE", "E", "/entry", "NXdemo_x#nE") in _codes(findings)


def test_type_units_and_link(tmp_path, demo_bundle):
    path = _write(tmp_path / "t.h5", energy_dtype="i8", units=False)
    with h5py.File(path, "a") as root:
        del root["entry/data/energy"]
        root["entry/data/energy"] = h5py.SoftLink("/entry/nothing")
    codes = _codes(validate(path, demo_bundle))
    assert (
        "TYPE",
        "E",
        "/entry/instrument/monochromator/energy",
        "NXdemo_x/ENTRY/INSTRUMENT/monochromator/energy",
    ) in codes
    assert (
        "UNITS",
        "W",
        "/entry/instrument/monochromator/energy",
        "NXdemo_x/ENTRY/INSTRUMENT/monochromator/energy",
    ) in codes
    assert ("LINK", "E", "/entry/data/energy", "NXdemo_x/ENTRY/DATA/energy") in codes


def test_wrong_link_target(tmp_path, demo_bundle):
    path = _write(tmp_path / "l.h5", soft=False)
    with h5py.File(path, "a") as root:
        root["entry/data/energy"] = h5py.SoftLink("/entry/data/mu")
    codes = _codes(validate(path, demo_bundle))
    assert ("LINK", "E", "/entry/data/energy", "NXdemo_x/ENTRY/DATA/energy") in codes


def test_enum_ref_class_and_undeclared(tmp_path, demo_bundle):
    path = _write(tmp_path / "e.h5")
    with h5py.File(path, "a") as root:
        root["entry/instrument/counter/mode"][...] = "other"
        del root["entry/instrument/counter/mode"]
        root["entry/instrument/counter/mode"] = "manual"
        root["entry/data"].attrs["signal"] = "nothing"
        root["entry/instrument/monochromator"].attrs["NX_class"] = "NXsample"
        root["entry"].create_group("extra")
    findings = validate(path, demo_bundle)
    codes = _codes(findings)
    assert (
        "ENUM",
        "E",
        "/entry/instrument/counter/mode",
        "NXdemo_x/ENTRY/INSTRUMENT/counter/mode",
    ) in codes
    assert ("ENUM", "E", "/entry/data@signal", "NXdemo_x/ENTRY/DATA@signal") in codes
    assert (
        "REF",
        "E",
        "/entry/data@signal",
        "NXdemo_x/ENTRY/DATA/DATA",
    ) in codes
    assert (
        "CLASS",
        "E",
        "/entry/instrument/monochromator",
        "NXdemo_x/ENTRY/INSTRUMENT/monochromator",
    ) in codes
    assert ("NO-CLASS", "W", "/entry/extra", None) in codes
    assert any(f.code == "UNDECLARED" and f.path == "/entry/extra" for f in findings)


def test_dispatch(tmp_path, demo_bundle):
    findings = validate(_write(tmp_path / "n.h5", definition=None), demo_bundle)
    assert ("NO-DEFINITION", "I", "/", None) in _codes(findings, ("I",))
    findings = validate(
        _write(tmp_path / "n2.h5", definition=None), demo_bundle, expect="NXdemo_x"
    )
    assert ("NO-DEFINITION", "E", "/", "NXdemo_x") in _codes(findings)
    findings = validate(_write(tmp_path / "u.h5", definition="NXunknown"), demo_bundle)
    assert ("UNKNOWN-DEFINITION", "W", "/entry/definition", None) in _codes(findings)


def test_constraint(tmp_path, demo_bundle):
    path = tmp_path / "c.h5"
    with h5py.File(path, "w") as root:
        entry = root.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry["definition"] = "NXdemo_z"
        data = entry.create_group("data")
        data.attrs["NX_class"] = "NXdata"
    codes = _codes(validate(path, demo_bundle))
    assert (
        "CONSTRAINT",
        "E",
        "/entry/data",
        "NXdemo_z/ENTRY/DATA:at_least_one_of[mu,fluo]",
    ) in codes
    assert ("BUNDLE", "I", "/", None) in _codes(validate(path, demo_bundle), ("I",))


def test_reads_only_small_values(tmp_path, demo_bundle, monkeypatch):
    """Tiers M and S: no dataset with more than one element is read."""
    path = _write(tmp_path / "lazy.h5", points=50, total=50)
    reads = []
    original = h5py.Dataset.__getitem__

    def spy(self, key):
        reads.append(self.size)
        return original(self, key)

    monkeypatch.setattr(h5py.Dataset, "__getitem__", spy)
    validate(path, demo_bundle)
    assert reads and max(reads) == 1


@pytest.mark.parametrize("partial", [False, True])
def test_findings_are_deterministic(tmp_path, demo_bundle, partial):
    path = _write(tmp_path / "d.h5", title=False)
    assert validate(path, demo_bundle, partial=partial) == validate(
        path, demo_bundle, partial=partial
    )


def test_validate_streams(tmp_path, demo_bundle):
    findings = _validate(_write(tmp_path / "s.h5", title=False), demo_bundle)
    assert isinstance(findings, Iterator)
    assert next(findings).code == "RECOMMENDED"  # before the walk is done
    findings.close()


def test_hard_link_with_target_is_a_link(tmp_path, demo_bundle):
    path = _write(tmp_path / "h.h5", soft=False)
    with h5py.File(path, "a") as root:
        energy = root["entry/instrument/monochromator/energy"]
        energy.attrs["target"] = "/entry/instrument/monochromator/energy"
        root["entry/data/energy"] = energy
    assert _codes(validate(path, demo_bundle)) == set()
    with h5py.File(path, "a") as root:
        del root["entry/data/energy"]
        root["entry/data/energy"] = root["entry/data/mu"]
        root["entry/data/mu"].attrs["target"] = "/entry/data/mu"
    codes = _codes(validate(path, demo_bundle))
    assert ("LINK", "E", "/entry/data/energy", "NXdemo_x/ENTRY/DATA/energy") in codes


def test_hard_link_without_target_is_an_object(tmp_path, demo_bundle):
    """Q8: without a target attribute, every path is an ordinary object."""
    path = _write(tmp_path / "o.h5", soft=False)
    with h5py.File(path, "a") as root:
        root["entry/data/energy"] = root["entry/instrument/monochromator/energy"]
    codes = _codes(validate(path, demo_bundle))
    assert ("MISSING", "E", "/entry/data", "NXdemo_x/ENTRY/DATA/energy") in codes


def test_external_links(tmp_path, demo_bundle):
    path = _write(tmp_path / "x.h5", soft=False)
    with h5py.File(tmp_path / "other.h5", "w") as other:
        other["energy"] = np.linspace(1, 2, 5)
    with h5py.File(path, "a") as root:
        root["entry/data/energy"] = h5py.ExternalLink("other.h5", "/energy")
        root["entry/data/missing"] = h5py.ExternalLink("nowhere.h5", "/energy")
    findings = validate(path, demo_bundle)
    skipped = {(f.code, f.path) for f in findings if f.severity == "I"}
    assert ("SKIPPED", "/entry/data/missing") in skipped
    assert not [f for f in findings if f.code == "LINK" and "missing" in f.path]
    # the object reached is not the monochromator energy
    assert ("LINK", "E", "/entry/data/energy", "NXdemo_x/ENTRY/DATA/energy") in _codes(
        findings
    )


def test_read_errors_never_stop(tmp_path, demo_bundle, monkeypatch):
    path = _write(tmp_path / "r.h5", title=False)

    def broken(self, key):
        raise OSError("can't read data (required filter is not available)")

    monkeypatch.setattr(h5py.Dataset, "__getitem__", broken)
    findings = validate(path, demo_bundle)
    skipped = ("SKIPPED", "I", "/entry/definition", "NXentry/definition")
    assert skipped in _codes(findings, "I")
    assert ("RECOMMENDED", "W", "/entry", "NXentry/title") not in _codes(findings)
    assert any(f.code == "UNDECLARED" for f in findings)  # the walk went on


def test_swmr_read_while_writing(tmp_path, demo_bundle):
    path = tmp_path / "w.h5"
    with h5py.File(path, "w", libver="latest") as writer:
        writer.attrs["NX_class"] = "NXroot"
        entry = writer.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry.create_dataset("counts", data=np.arange(3), maxshape=(None,))
        writer.swmr_mode = True
        findings = validate(path, demo_bundle, partial=True)
    assert ("NO-DEFINITION", "I", "/", None) not in _codes(findings, "I")
    assert any(f.code == "INCOMPLETE" and f.path == "/" for f in findings)


def test_finding_follows_the_metaschema(tmp_path, demo_bundle):
    for finding in validate(_write(tmp_path / "m.h5", signal=False), demo_bundle):
        data = json.loads(finding_json(finding))
        assert "member" in data
        assert Finding.model_validate(data) == finding


def test_no_class_by_exact_name(tmp_path, demo_bundle):
    path = _write(tmp_path / "c.h5")
    with h5py.File(path, "a") as root:
        del root["entry/instrument/monochromator"].attrs["NX_class"]
    found = [f for f in validate(path, demo_bundle) if f.code == "NO-CLASS"]
    assert [(f.path, f.member) for f in found] == [
        (
            "/entry/instrument/monochromator",
            "NXdemo_x/ENTRY/INSTRUMENT/monochromator",
        )
    ]


def test_dimension_expressions():
    assert _evaluate("2*n+1", {"n": 3}) == 7
    assert _evaluate("tof-1", {"tof": 3}) == 2
    with pytest.raises(ValueError):
        _evaluate("n/2", {"n": 4})


def test_link_to_an_object_walked_before(tmp_path, demo_bundle):
    """The target is walked before the link: its assignment is found again."""
    path = _write(tmp_path / "b.h5")
    with h5py.File(path, "a") as root:
        root.move("entry/data", "entry/zdata")
    assert not [f for f in validate(path, demo_bundle) if f.code == "LINK"]
    with h5py.File(path, "a") as root:
        del root["entry/zdata/energy"]
        root["entry/zdata/energy"] = h5py.SoftLink("/entry/instrument/counter/mode")
    codes = _codes(validate(path, demo_bundle))
    assert ("LINK", "E", "/entry/zdata/energy", "NXdemo_x/ENTRY/DATA/energy") in codes


def test_catalogue(tmp_path, demo_build):
    from nxds_tools._build import write_bundle_directory
    from nxds_tools.bundle import select_bundle

    write_bundle_directory(demo_build, tmp_path / "r1")
    (tmp_path / "nxds-index.json").write_text(
        json.dumps(
            {
                "bundles": [
                    {
                        "release": "v2026.01",
                        "revision": 1,
                        "status": "current",
                        "path": "r1",
                    },
                    {
                        "release": "v2026.01",
                        "revision": 2,
                        "status": "withdrawn",
                        "path": "r2",
                    },
                ]
            }
        )
    )
    assert select_bundle(tmp_path, "2026.01.post1") == (tmp_path / "r1", True)
    assert select_bundle(tmp_path, "v2099.01") == (tmp_path / "r1", False)
    path = _write(tmp_path / "c.h5")
    found = validate(path, select_bundle(tmp_path, "v2026.01")[0])
    assert _codes(found) == set()
