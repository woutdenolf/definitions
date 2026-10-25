"""NXcase_link_refines: links through a refining member."""

import sys

import h5py
import numpy as np
from _common import add_entry
from _common import group

root = h5py.File(sys.argv[1], "w")
root.attrs["NX_class"] = "NXroot"
entry = add_entry(root, "entry", "NXcase_link_refines")
mono = group(
    group(entry, "instrument", "NXinstrument"), "monochromator", "NXmonochromator"
)
mono["energy"] = np.linspace(7.0, 7.2, 3)
mono["energy"].attrs["units"] = "keV"
mono["wavelength"] = np.linspace(1.7, 1.8, 3)
sample = group(entry, "sample", "NXcase_sample")
sample["temperature"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
data = group(entry, "data", "NXdata")
data["wavelength"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
root.close()
