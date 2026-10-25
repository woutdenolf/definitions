"""NXcase_nxdl while it is being written: title and @signal not yet there."""

import sys

import h5py
from _common import energy
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
energy(entry, 5, resizable=True)
data = group(entry, "data", "NXdata")
data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
root.close()
