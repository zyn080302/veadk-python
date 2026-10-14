# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Optional activation, backend selection and legacy import contracts."""

import importlib
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from veadk.extensions.aiops import AIOpsExtension, AgentConfig, AgentPlugin
from veadk.extensions.aiops import backend as loader


def registration(name, value, loaded):
    def load():
        loaded.append(name)
        return value

    return SimpleNamespace(name=name, load=load)


def backend(calls):
    def create_agent(config, plugins, *, agent=None, **kwargs):
        calls.append((config, plugins, agent, kwargs))
        return agent if agent is not None else object()

    return SimpleNamespace(
        api_version=1, create_agent=create_agent, create_app=create_agent
    )


def test_import_and_construction_never_load_core_or_discover_plugins():
    code = """
import importlib.abc, importlib.metadata, sys
class BlockCore(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("agentkit_aiops"):
            raise AssertionError("implicit Core import")
sys.meta_path.insert(0, BlockCore())
original = importlib.metadata.entry_points
def points(*args, **kwargs):
    assert kwargs.get("group") != "veadk.aiops.backends", "implicit discovery"
    return original(*args, **kwargs)
importlib.metadata.entry_points = points
from veadk import Agent
from veadk.extensions.aiops import AIOpsExtension
from veadk.aiops.hosting import create_agent
AIOpsExtension()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHON_DOTENV_DISABLED": "1", "OTEL_SDK_DISABLED": "true"},
        timeout=90,
    )
    assert result.returncode == 0, result.stderr


def test_disabled_apply_is_exact_noop(monkeypatch):
    monkeypatch.setattr(loader, "entry_points", lambda **kw: pytest.fail("discovery"))
    agent = object()
    extension = AIOpsExtension(
        enabled=False,
        plugins=[
            AgentPlugin("domain", tools_factory=lambda ctx: pytest.fail("factory"))
        ],
    )
    assert extension.apply(agent) is agent
    with pytest.raises(RuntimeError, match="disabled"):
        extension.create_agent()
    with pytest.raises(RuntimeError, match="disabled"):
        extension.create_app()


@pytest.mark.parametrize("name", ["", " ", "../../module", "module:call"])
def test_backend_name_is_not_an_import_expression(name):
    with pytest.raises(ValueError, match="backend"):
        AIOpsExtension(backend=name)


def test_selected_registration_loads_once_and_keeps_domain_objects(monkeypatch):
    calls, loaded = [], []
    engine = backend(calls)
    entries = [
        registration("chosen", engine, loaded),
        registration("other", None, loaded),
    ]
    monkeypatch.setattr(loader, "entry_points", lambda **kw: entries)
    config = AgentConfig(name="domain")
    plugin = AgentPlugin("domain")
    extension = AIOpsExtension(config, [plugin], backend="chosen")
    first, second = object(), object()
    assert extension.apply(first) is first
    assert extension.apply(second) is second
    extension.create_app()
    assert loaded == ["chosen"]
    assert all(c[:2] == (config, (plugin,)) for c in calls)
    assert calls[0][2] is first and calls[1][2] is second


def test_duplicate_selected_names_fail_before_loading(monkeypatch):
    loaded = []
    monkeypatch.setattr(
        loader,
        "entry_points",
        lambda **kw: [
            registration("agentkit", backend([]), loaded),
            registration("agentkit", backend([]), loaded),
        ],
    )
    with pytest.raises(RuntimeError, match="Multiple"):
        AIOpsExtension().create_agent()
    assert not loaded


def test_unknown_backend_does_not_load_legacy_package(monkeypatch):
    monkeypatch.setattr(loader, "entry_points", lambda **kw: [])
    monkeypatch.setattr(loader, "import_module", lambda *a: pytest.fail("fallback"))
    with pytest.raises(RuntimeError, match="not installed"):
        AIOpsExtension(backend="unknown").create_agent()


def test_missing_core_has_actionable_error(monkeypatch):
    monkeypatch.setattr(loader, "entry_points", lambda **kw: [])

    def missing(name):
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(loader, "import_module", missing)
    with pytest.raises(RuntimeError, match="separately installed"):
        AIOpsExtension().create_agent()


def test_nested_dependency_error_is_not_reported_as_core_absence(monkeypatch):
    monkeypatch.setattr(loader, "entry_points", lambda **kw: [])

    def missing(name):
        raise ModuleNotFoundError(name="transitive_dependency")

    monkeypatch.setattr(loader, "import_module", missing)
    with pytest.raises(ModuleNotFoundError) as exc:
        AIOpsExtension().create_agent()
    assert exc.value.name == "transitive_dependency"


def test_registered_failure_never_falls_back(monkeypatch):
    def fail():
        raise RuntimeError("backend initialization failed")

    monkeypatch.setattr(
        loader,
        "entry_points",
        lambda **kw: [SimpleNamespace(name="agentkit", load=fail)],
    )
    monkeypatch.setattr(loader, "import_module", lambda *a: pytest.fail("fallback"))
    with pytest.raises(RuntimeError, match="initialization failed"):
        AIOpsExtension().create_agent()


@pytest.mark.parametrize(
    "engine",
    [
        object(),
        SimpleNamespace(api_version=2),
        SimpleNamespace(
            api_version=True, create_agent=lambda: None, create_app=lambda: None
        ),
        SimpleNamespace(api_version=1, create_agent=None, create_app=lambda: None),
    ],
)
def test_backend_api_is_validated_before_use(monkeypatch, engine):
    monkeypatch.setattr(
        loader, "entry_points", lambda **kw: [registration("agentkit", engine, [])]
    )
    with pytest.raises(RuntimeError, match="API"):
        AIOpsExtension().create_agent()


def test_legacy_core_fallback_preserves_config_and_plugins(monkeypatch):
    calls = []
    engine = backend(calls)
    del engine.api_version
    monkeypatch.setattr(loader, "entry_points", lambda **kw: [])
    monkeypatch.setattr(
        loader,
        "import_module",
        lambda name: engine if name == "agentkit_aiops" else pytest.fail(name),
    )
    config = AgentConfig(name="legacy")
    AIOpsExtension(config).create_agent()
    assert calls[0][:2] == (config, ())


def test_report_only_is_rejected_before_loading_core(monkeypatch):
    monkeypatch.setattr(loader, "entry_points", lambda **kw: pytest.fail("discovery"))
    with pytest.raises(ValueError, match="report_only"):
        AIOpsExtension(AgentConfig(report_only=True)).create_agent()


def test_legacy_imports_are_same_types():
    for module, names in {
        "config": ["AgentConfig"],
        "plugin": ["AgentPlugin", "BuildContext"],
        "manifest": ["AgentManifest"],
    }.items():
        old = importlib.import_module("veadk.aiops." + module)
        new = importlib.import_module("veadk.extensions.aiops." + module)
        for name in names:
            assert getattr(old, name) is getattr(new, name)


def test_real_installed_entry_point_selection(tmp_path, monkeypatch):
    """Exercise importlib.metadata against a real distribution record."""
    dist = tmp_path / "fixture_aiops_backend-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Name: fixture-aiops-backend\nVersion: 1.0\n")
    (dist / "entry_points.txt").write_text(
        "[veadk.aiops.backends]\nfixture_contract = fixture_aiops_backend:backend\n"
    )
    (tmp_path / "fixture_aiops_backend.py").write_text(
        "from types import SimpleNamespace\n"
        "def compose(config, plugins, *, agent=None):\n"
        "    return (config.name, len(plugins), agent)\n"
        "backend = SimpleNamespace(api_version=1, create_agent=compose, create_app=compose)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    extension = AIOpsExtension(
        AgentConfig(name="installed"), backend="fixture_contract"
    )
    agent = object()
    try:
        assert extension.apply(agent) == ("installed", 0, agent)
    finally:
        sys.modules.pop("fixture_aiops_backend", None)


def test_old_sdk_rejected_before_backend_loading(monkeypatch):
    from veadk.runtime.codex.config import CodexRuntimeConfig

    fields = dict(CodexRuntimeConfig.model_fields)
    fields.pop("provider_factory")
    monkeypatch.setattr(CodexRuntimeConfig, "__pydantic_fields__", fields)
    monkeypatch.setattr(loader, "entry_points", lambda **kw: pytest.fail("discovery"))
    with pytest.raises(RuntimeError, match="public Codex provider API"):
        AIOpsExtension().create_agent()
