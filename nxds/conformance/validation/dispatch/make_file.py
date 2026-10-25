"""Entries following NXcase_nxdl, NXcase_require and an unknown definition."""

import sys

import h5py
from _common import add_entry
from _common import energy
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
entry = add_entry(root, "entry1", "NXcase_nxdl")
entry["title"] = "scan"
energy(entry, 5)
data = group(entry, "data", "NXdata")
data.attrs["signal"] = "energy"
data["energy"] = h5py.SoftLink("/entry1/instrument/monochromator/energy")
group(add_entry(root, "entry2", "NXcase_require"), "data", "NXdata")
add_entry(root, "entry3", "NXcase_unknown")
root.close()
