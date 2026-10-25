"""Helpers for the scripts that write the validation fixtures (h5py)."""

import h5py
import numpy as np


def group(parent: h5py.Group, name: str, nx_class: str) -> h5py.Group:
    created = parent.create_group(name)
    created.attrs["NX_class"] = nx_class
    return created


def entry_file(path: str, definition: str) -> tuple[h5py.File, h5py.Group]:
    root = h5py.File(path, "w")
    root.attrs["NX_class"] = "NXroot"
    entry = group(root, "entry", "NXentry")
    entry["definition"] = definition
    return root, entry


def energy(parent: h5py.Group, n: int, resizable: bool = False) -> None:
    mono = group(
        group(parent, "instrument", "NXinstrument"), "monochromator", "NXmonochromator"
    )
    mono.create_dataset(
        "energy", data=np.linspace(7.0, 7.2, n), maxshape=(None,) if resizable else None
    )
    mono["energy"].attrs["units"] = "keV"


def add_entry(root: h5py.Group, name: str, definition: str) -> h5py.Group:
    entry = group(root, name, "NXentry")
    entry["definition"] = definition
    return entry
