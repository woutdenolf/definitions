"""NXcase_enum_nxdl with an integer enumeration."""

import sys

import h5py
import numpy as np
from _common import add_entry
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
for name, mode in (("entry1", np.int64(4)), ("entry2", np.int8(5))):
    probe = group(add_entry(root, name, "NXcase_enum_nxdl"), "probe", "NXcase_probe")
    probe["mode"] = mode
    probe["labels"] = np.array([b"a", b"b"])
    probe["direction"] = np.array([0, 0, 1])
root.close()
