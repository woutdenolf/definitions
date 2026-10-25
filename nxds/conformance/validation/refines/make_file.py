"""NXcase_refines with three channel counters where two are allowed."""

import sys

import numpy as np
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_refines")
counter = group(group(entry, "instrument", "NXinstrument"), "counter", "NXcounter")
counter["mode"] = "timer"
for name in ("i0_counts", "i2_counts", "i3_counts"):
    counter[name] = np.zeros(3, dtype="i4")
    counter[name].attrs["units"] = ""
root.close()
