"""NXcase_link_refines: a dataset where a link is required."""

import sys

import h5py
import numpy as np
from _common import add_entry
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
for name, linked in (("entry1", False), ("entry2", True)):
    entry = add_entry(root, name, "NXcase_link_refines")
    instrument = group(entry, "instrument", "NXinstrument")
    mono = group(instrument, "monochromator", "NXmonochromator")
    mono["energy"] = np.linspace(7.0, 7.2, 3)
    mono["energy"].attrs["units"] = "keV"
    mono["wavelength"] = np.linspace(1.7, 1.8, 3)
    sample = group(entry, "sample", "NXcase_sample")
    if linked:
        sample["temperature"] = h5py.SoftLink(
            f"/{name}/instrument/monochromator/energy"
        )
    else:
        sample["temperature"] = 300.0
    data = group(entry, "data", "NXdata")
    data["wavelength"] = h5py.SoftLink(f"/{name}/instrument/monochromator/wavelength")
root.close()
