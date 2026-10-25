"""NXcase_name_fit with a float channel counter and an unknown counting mode."""

import sys

import numpy as np
from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_name_fit")
instrument = group(entry, "instrument", "NXinstrument")
group(instrument, "monochromator", "NXmonochromator")
counter = group(instrument, "counter", "NXcounter")
counter["mode"] = "manual"
counter["i0_counts"] = np.zeros(3, dtype="f8")
counter["i0_counts"].attrs["units"] = ""
counter["i1_counts"] = np.zeros(3, dtype="i4")
root.close()
