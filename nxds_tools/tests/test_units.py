import pytest

from nxds_tools._units import UnitsError
from nxds_tools._units import dimensions
from nxds_tools._units import normalise


@pytest.mark.parametrize(
    "units, expected",
    [
        ("", {}),
        ("m", {"length": 1}),
        ("keV", {"length": 2, "mass": 1, "time": -2}),
        ("1/(angstrom^2*s)", {"length": -2, "time": -1}),
        ("g/cm^3", {"length": -3, "mass": 1}),
        ("m s-1", {"length": 1, "time": -1}),
        ("deg", {"angle": 1}),
        ("m/m", {}),
    ],
)
def test_dimensions(units, expected):
    assert dimensions(units) == expected


def test_unknown_units():
    with pytest.raises(UnitsError):
        dimensions("furlong/fortnight")


def test_normalise():
    assert normalise("m/s") == normalise("m*s^-1") == normalise("m s-1")
    assert normalise("mm") != normalise("m")
    assert dimensions("mm") == dimensions("m")
