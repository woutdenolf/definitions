from pathlib import Path
from typing import Iterator
from typing import Optional
from typing import Tuple

from ..globals.directories import get_build_root
from ..globals.directories import get_nxdl_root

#: directories that hold no class definitions of the repository
IGNORED_DIRECTORIES = ("wip", "nxds", "nxds_tools")


def iter_definitions(*subdirs: Tuple[str]) -> Iterator[Path]:
    """Yield all NeXus class definitions"""
    nxdl_root = root = get_nxdl_root()
    build_root = get_build_root()
    # the NXDL root may itself be a tree generated in the build root
    skip_build = not _is_relative_to(nxdl_root, build_root)
    for subdir in subdirs:
        root /= subdir
    for path in sorted(root.rglob("*.nxdl.xml")):
        if skip_build and _is_relative_to(path, build_root):
            continue
        if path.relative_to(nxdl_root).parts[0] in IGNORED_DIRECTORIES:
            continue
        yield path


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


def find_definition(nxclass: str, *subdirs: Tuple[str]) -> Optional[Path]:
    """Find the definition of a NeXus class"""
    s = nxclass.lower() + ".nxdl"
    for path in iter_definitions(*subdirs):
        if path.stem.lower() == s:
            return path
