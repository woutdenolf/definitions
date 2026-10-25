"""Two entries following NXcase_choice, with shapes of different classes."""

import sys

import h5py
from _common import add_entry
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
shape = group(add_entry(root, "entry1", "NXcase_choice"), "shape", "NXcase_cylinder")
shape["radius"] = "two"
group(add_entry(root, "entry2", "NXcase_choice"), "shape", "NXsensor")
root.close()
