"""Require real SDK terminal regressions without silently skipped cases."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if importlib.metadata.version("openai-codex") != "0.163.0":
        raise SystemExit("Terminal gate requires the fixed official SDK 0.163.0")
    with tempfile.TemporaryDirectory(prefix="codex-terminal-gate-") as directory:
        report = Path(directory) / "results.xml"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/runtime/codex/test_codex_terminal_integrity.py",
                "tests/runtime/codex/test_codex_turn_contract.py::test_selected_binary_change_invalidates_the_warm_process",
                "-m",
                "not codex_smoke",
                "-p",
                "no:xdist",
                "-q",
                f"--junitxml={report}",
            ],
            cwd=ROOT,
        )
        if result.returncode or not report.exists():
            raise SystemExit("Codex terminal integrity gate failed")
        cases = list(ET.parse(report).getroot().iter("testcase"))
        if len(cases) < 25 or any(
            case.find(tag) is not None
            for case in cases
            for tag in ("skipped", "failure", "error")
        ):
            raise SystemExit(
                "Codex terminal integrity gate did not run every required case"
            )
        print(f"Codex terminal integrity: {len(cases)} required cases passed")


if __name__ == "__main__":
    main()
