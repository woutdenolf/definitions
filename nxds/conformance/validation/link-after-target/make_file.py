"""NXcase_nxdl whose NXdata comes after the instrument in byte order."""

import sys

import h5py
from _common import energy
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
entry["title"] = "scan"
energy(entry, 5)
data = group(entry, "zdata", "NXdata")
data.attrs["signal"] = "energy"
data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
root.close()
