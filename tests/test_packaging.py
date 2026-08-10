import tomllib
from pathlib import Path

import app

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    metadata = tomllib.loads(PYPROJECT.read_text())
    assert app.__version__ == metadata["project"]["version"]
