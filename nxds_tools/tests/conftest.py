import os
from pathlib import Path

import pytest

from nxds_tools._build import BuildResult
from nxds_tools._build import build
from nxds_tools._xsd import XsdFacts
from nxds_tools._xsd import load_facts

from .demo import write_demo


@pytest.fixture(scope="session")
def definitions() -> Path:
    """The definitions repository this project lives in (or NXDS_DEFINITIONS)."""
    path = Path(os.environ.get("NXDS_DEFINITIONS", Path(__file__).resolve().parents[2]))
    if not (path / "nxdl.xsd").exists():
        pytest.skip(f"no definitions repository at {path}")
    return path


@pytest.fixture(scope="session")
def facts(definitions: Path) -> XsdFacts:
    return load_facts(definitions)


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_demo(tmp_path_factory.mktemp("demo") / "demo")


@pytest.fixture(scope="session")
def demo_build(definitions: Path, demo_dir: Path) -> BuildResult:
    """The whole corpus plus the demo classes, resolved once per session."""
    return build(definitions, [demo_dir])


@pytest.fixture(scope="session")
def demo_bundle(demo_build: BuildResult):
    return demo_build.bundle()
