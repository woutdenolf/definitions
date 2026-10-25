"""NXcase_nxdl whose NXdata/energy points into a missing file."""

import sys

import h5py
from _common import energy
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
entry["title"] = "scan"
energy(entry, 5)
data = group(entry, "data", "NXdata")
data.attrs["signal"] = "energy"
data["energy"] = h5py.ExternalLink(
    "no_such_file.h5", "/entry/instrument/monochromator/energy"
)
root.close()
