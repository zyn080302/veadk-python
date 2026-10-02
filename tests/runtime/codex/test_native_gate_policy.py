"""Exercise pytest selection and the existing strict JUnit release verifier."""

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from verify_native_report import REQUIRED_MODULES, REQUIRED_PARALLEL_CASES, verify


@pytest.mark.parametrize(
    "partition, marker, expected",
    [
        ("1", "codex_native", 1),
        ("1", "not codex_native", 2),
        ("0", "not codex_native", 3),
    ],
)
def test_real_pytest_partitions_required_modules_without_cross_directory_leakage(
    tmp_path, partition, marker, expected
):
    source = Path(__file__).parent
    group = tmp_path / "native"
    group.mkdir()
    for name in ("conftest.py", "verify_native_report.py"):
        (group / name).write_bytes((source / name).read_bytes())
    required_name = sorted(REQUIRED_MODULES)[0] + ".py"
    (group / required_name).write_text("def test_required(): pass\n")
    (group / "test_regular.py").write_text("def test_regular(): pass\n")
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / required_name).write_text("def test_unrelated_same_filename(): pass\n")
    env = {
        k: os.environ[k] for k in ("PATH", "HOME", "UV_CACHE_DIR") if k in os.environ
    }
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = str(group)
    env["VEADK_NATIVE_GATE_PARTITION"] = partition
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--offline",
            "--no-project",
            "--python",
            sys.executable,
            "python",
            "-m",
            "pytest",
            "--import-mode=importlib",
            "-q",
            "-m",
            marker,
            "--junitxml=" + str(tmp_path / "result.xml"),
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0
    cases = list(ET.parse(tmp_path / "result.xml").getroot().iter("testcase"))
    assert len(cases) == expected
    names = {case.get("name") for case in cases}
    if partition == "0":
        assert names == {
            "test_required",
            "test_regular",
            "test_unrelated_same_filename",
        }
    else:
        assert names == (
            {"test_required"}
            if marker == "codex_native"
            else {"test_regular", "test_unrelated_same_filename"}
        )


def _report(path):
    suite = ET.Element("testsuite")
    for module in sorted(REQUIRED_MODULES):
        ET.SubElement(suite, "testcase", classname=module, name="test_unit")
    for name in sorted(REQUIRED_PARALLEL_CASES):
        ET.SubElement(
            suite, "testcase", classname="test_codex_native_multi_mcp", name=name
        )
    for index in range(10):
        ET.SubElement(
            suite,
            "testcase",
            classname="test_codex_native_cli",
            name=f"test_cli_{index}",
        )
    ET.SubElement(
        suite,
        "testcase",
        classname="test_codex_native_cli",
        name="test_native_cli_through_python_sdk_http",
    )
    ET.ElementTree(suite).write(path)
    return suite


@pytest.mark.parametrize(
    "defect",
    [
        "failure",
        "error",
        "skipped",
        "missing_module",
        "missing_http",
        "missing_parallel",
    ],
)
def test_native_verifier_still_rejects_incomplete_or_non_green_evidence(
    tmp_path, defect
):
    path = tmp_path / "report.xml"
    suite = _report(path)
    verify(path)
    if defect in {"failure", "error", "skipped"}:
        ET.SubElement(suite[0], defect)
    elif defect == "missing_module":
        for case in list(suite):
            if case.get("classname") == "test_codex_native_multi_mcp":
                suite.remove(case)
    elif defect == "missing_parallel":
        suite.remove(next(c for c in suite if c.get("name") in REQUIRED_PARALLEL_CASES))
    else:
        suite.remove(
            next(
                c
                for c in suite
                if c.get("name") == "test_native_cli_through_python_sdk_http"
            )
        )
    ET.ElementTree(suite).write(path)
    with pytest.raises(RuntimeError, match="Native Codex gate"):
        verify(path)
