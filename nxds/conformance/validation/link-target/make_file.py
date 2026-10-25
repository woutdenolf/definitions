"""NXcase_nxdl whose NXdata/energy links to the wrong object."""

import sys

import h5py
from _common import energy
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
entry["title"] = "scan"
entry["start_time"] = "2026-10-03T12:00:00"
energy(entry, 5)
data = group(entry, "data", "NXdata")
data.attrs["signal"] = "energy"
data["energy"] = h5py.SoftLink("/entry/title")
root.close()
