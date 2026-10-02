"""Fail the native release gate on missing, skipped, failed, or errored tests."""

import sys
import xml.etree.ElementTree as ET


REQUIRED_MODULES = {
    "test_codex_native_cli",
    "test_codex_native_bridge",
    "test_codex_native_session",
    "test_codex_native_lifecycle",
    "test_codex_native_transport",
    "test_codex_native_response_fields",
    "test_codex_native_request_history",
    "test_codex_tool_wire",
    "test_codex_native_final_selection",
    "test_codex_native_multi_mcp",
    "test_codex_native_tool_metadata",
}

REQUIRED_PARALLEL_CASES = {
    f"test_explicit_server_parallelism_preserves_provider_annotations[{hint}]"
    for hint in ("missing", "false")
}


def verify(path):
    entries = list(ET.parse(path).getroot().iter("testcase"))
    if any(
        case.find(tag) is not None
        for case in entries
        for tag in ("failure", "error", "skipped")
    ):
        raise RuntimeError("Native Codex gate contains a failure, error, or skip")

    seen = {case.get("classname", "").split(".")[-1] for case in entries}
    if REQUIRED_MODULES - seen:
        raise RuntimeError("Native Codex gate is missing required modules")
    parallel = {
        case.get("name")
        for case in entries
        if case.get("classname", "").endswith("test_codex_native_multi_mcp")
    }
    if REQUIRED_PARALLEL_CASES - parallel:
        raise RuntimeError("Native Codex gate is missing service parallelism cases")
    cli = [
        case
        for case in entries
        if case.get("classname", "").endswith("test_codex_native_cli")
    ]
    if len(cli) < 11 or not any(
        case.get("name") == "test_native_cli_through_python_sdk_http" for case in cli
    ):
        raise RuntimeError("Native Codex gate did not run all required real CLI cases")
    print(
        f"Native Codex gate passed: {len(entries)} tests, including {len(cli)} real CLI cases"
    )


if __name__ == "__main__":
    verify(sys.argv[1])
