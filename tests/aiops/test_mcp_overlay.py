"""Custom applications keep ownership of their MCP policy wrappers."""

from types import SimpleNamespace

import pytest

from veadk.cli.legacy_runtime_recovery import _SITECUSTOMIZE


def replace_mcp():
    namespace = {}
    # Exercise the actual generated functions without installing a process hook.
    source = _SITECUSTOMIZE.rsplit("\n_install()", 1)[0]
    exec(compile(source, "studio-overlay-test", "exec"), namespace)
    return namespace["_replace_mcp"]


def test_custom_handler_retains_wrappers_and_visits_children():
    wrapper = object()
    observed = []
    child = SimpleNamespace(
        name="child",
        tools=[wrapper],
        sub_agents=[],
        _veadk_studio_mcp_overlay_handler=observed.append,
    )
    root = SimpleNamespace(name="root", tools=[], sub_agents=[child])
    selection = [
        {
            "name": "fixture",
            "transport": "http",
            "url": "https://fixture.invalid/mcp",
            "authTokenEnv": "MISSING_FIXTURE_TOKEN",
        }
    ]
    replace_mcp()(root, {"child": selection})
    assert observed == [selection]
    assert child.tools == [wrapper]


def test_custom_handler_failure_does_not_fall_back_to_bare_mcp():
    wrapper = object()

    def refuse(entries):
        raise RuntimeError("domain policy refused")

    root = SimpleNamespace(
        name="root",
        tools=[wrapper],
        sub_agents=[],
        _veadk_studio_mcp_overlay_handler=refuse,
    )
    with pytest.raises(RuntimeError, match="domain policy refused"):
        replace_mcp()(root, {"root": []})
    assert root.tools == [wrapper]


def test_non_callable_handler_is_rejected():
    root = SimpleNamespace(
        name="root", tools=[], sub_agents=[], _veadk_studio_mcp_overlay_handler=True
    )
    with pytest.raises(RuntimeError, match="handler is invalid"):
        replace_mcp()(root, {"root": []})
