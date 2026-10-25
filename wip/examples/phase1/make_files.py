"""Write the two small example files of phase 1 (proposal §5).

- ``demo_phase1.h5``: complete, but NXdata lacks ``@signal`` and the entry has no ``title``;
- ``demo_phase1_partial.h5``: the same file while it is being written (57 of 200 points).
"""

import sys
from pathlib import Path

import h5py
import numpy as np


def write(path: Path, points: int, total: int = 200) -> None:
    energy = np.linspace(7000.0, 7200.0, total)
    with h5py.File(path, "w") as root:
        root.attrs["NX_class"] = "NXroot"
        root.attrs["NeXus_release"] = "v2026.01"
        entry = root.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry["definition"] = "NXdemo_phase1"
        instrument = entry.create_group("instrument")
        instrument.attrs["NX_class"] = "NXinstrument"
        mono = instrument.create_group("monochromator")
        mono.attrs["NX_class"] = "NXmonochromator"
        mono["energy"] = energy
        mono["energy"].attrs["units"] = "eV"
        counter = instrument.create_group("counter")
        counter.attrs["NX_class"] = "NXdemo_counter_phase1"
        counter["mode"] = "timer"
        counts = counter.create_dataset(
            "i0_counts", data=np.arange(points, dtype=np.int32), maxshape=(None,)
        )
        counts.attrs["units"] = ""
        data = entry.create_group("data")
        data.attrs["NX_class"] = "NXdata"
        data.create_dataset(
            "mu", data=np.random.default_rng(1).random(points), maxshape=(None,)
        )
        data["energy"] = h5py.SoftLink("/entry/instrument/monochromator/energy")


if __name__ == "__main__":
    here = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    write(here / "demo_phase1.h5", 200)
    write(here / "demo_phase1_partial.h5", 57)
