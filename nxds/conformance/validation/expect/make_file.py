"""An entry without definition, validated with expect."""

import sys

import h5py
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
group(root, "entry", "NXentry")
root.close()
