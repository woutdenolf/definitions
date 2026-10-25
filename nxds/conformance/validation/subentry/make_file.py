"""NXcase_outer with a subentry following NXcase_inner."""

import sys

import h5py
from _common import add_entry
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
entry = add_entry(root, "entry", "NXcase_outer")
sub = group(entry, "sub", "NXsubentry")
sub["definition"] = "NXcase_inner"
root.close()
