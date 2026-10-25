"""NXcase_nxdl whose @signal names a missing child."""

import sys

import h5py
from _common import energy
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
entry["title"] = "scan"
energy(entry, 5)
data = group(entry, "data", "NXdata")
data.attrs["signal"] = "absorbance"
data.attrs["axes"] = [".", "energy"]
data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
root.close()
