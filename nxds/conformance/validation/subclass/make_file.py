"""NXcase_subclass with a group of a subclass."""

import sys

import h5py
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_subclass")
crate = group(entry, "crate", "NXcase_lidded_crate")
crate["size"] = 1.5
crate["lid"] = "open"
crate.attrs["colour"] = "blue"
# a link after its target in walk order: the target is found again (§9.8)
data = group(entry, "zdata", "NXdata")
data["size"] = h5py.SoftLink("/entry/crate/size")
root.close()
