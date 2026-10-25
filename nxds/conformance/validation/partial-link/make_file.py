"""NXcase_nxdl while it is being written: the link target does not exist yet."""

import sys

import h5py
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
entry["title"] = "scan"
data = group(entry, "data", "NXdata")
data.attrs["signal"] = "energy"
data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
root.close()
