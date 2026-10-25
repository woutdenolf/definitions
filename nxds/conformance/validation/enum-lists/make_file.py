"""NXcase_enum with list-valued and per-element enumerations."""

import sys

import numpy as np
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_enum")
for name, axes, flags in (
    ("data1", [".", "x"], ["a", "b"]),
    ("data2", ["x", "."], ["a", "c"]),
):
    data = group(entry, name, "NXdata")
    data.attrs["axes"] = axes
    data.attrs["flags"] = flags
    data["x"] = np.arange(3.0)
root.close()
