"""NXcase_nxdl whose monochromator lives in another file (written next to it)."""

import sys
from pathlib import Path

import h5py
import numpy as np
from _common import entry_file
from _common import group

other = Path(sys.argv[1]).with_name("other.h5")
with h5py.File(other, "w") as handle:
    mono = group(handle, "mono", "NXmonochromator")
    mono["energy"] = np.linspace(7.0, 7.2, 5)
    mono["energy"].attrs["units"] = "keV"
root, entry = entry_file(sys.argv[1], "NXcase_nxdl")
entry["title"] = "scan"
instrument = group(entry, "instrument", "NXinstrument")
instrument["monochromator"] = h5py.ExternalLink("other.h5", "/mono")
data = group(entry, "zdata", "NXdata")
data.attrs["signal"] = "energy"
data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")
root.close()
