"""Keep the mandatory native gate disjoint from the ordinary unit-test job."""

import os
from pathlib import Path

import pytest
from verify_native_report import REQUIRED_MODULES


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    # Only opt in where a mandatory native job covers this same Python version.
    if os.environ.get("VEADK_NATIVE_GATE_PARTITION") != "1":
        return
    directory = Path(__file__).resolve().parent
    for item in items:
        path = Path(item.path).resolve()
        if path.parent == directory and path.stem in REQUIRED_MODULES:
            item.add_marker(pytest.mark.codex_native)
