"""Entries following NXcase_symbols whose datasets disagree about n."""

import sys

import h5py
import numpy as np
from _common import add_entry

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
# entry1: x and y disagree; entry2: the same in a stopped entry (contiguous data);
# entry3: x and y agree, the expression 2*n does not hold, stopped entry
for name, stopped, lengths in (
    ("entry1", False, (3, 4, 6)),
    ("entry2", True, (3, 4, 6)),
    ("entry3", True, (3, 3, 7)),
):
    entry = add_entry(root, name, "NXcase_symbols")
    if stopped:
        entry.attrs["status"] = "aborted"
    for dataset, length in zip(("x", "y", "xy"), lengths, strict=True):
        entry[dataset] = np.zeros(length)
root.close()
