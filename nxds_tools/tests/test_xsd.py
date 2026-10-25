def test_defaults_from_xsd(facts):
    assert facts.default("field", "type") == "NX_CHAR"
    assert facts.default("attribute", "optional") == "true"
    assert facts.default("group", "minOccurs") == "0"


def test_type_lattice(facts):
    assert facts.is_narrower("NX_INT", "NX_NUMBER")
    assert facts.is_narrower("NX_POSINT", "NX_INT")
    assert facts.is_narrower("NX_UINT", "NX_INT")
    assert not facts.is_narrower("NX_INT", "NX_UINT")
    assert not facts.is_narrower("NX_CHAR", "NX_FLOAT")
    assert facts.types["NX_QUATERNION"].length == 4


def test_units_categories(facts):
    energy = facts.units["NX_ENERGY"]
    assert energy.dimensions == [{"length": 2, "mass": 1, "time": -2}]
    assert facts.units["NX_ANY"].dimensions is None
    assert len(facts.units["NX_TRANSFORMATION"].dimensions) == 3


def test_name_grammar(facts):
    assert facts.names.item_max_length == 63
    assert facts.placeholder_characters.startswith("[")
    assert facts.units["NX_COUNT"].empty and not facts.units["NX_ENERGY"].empty
