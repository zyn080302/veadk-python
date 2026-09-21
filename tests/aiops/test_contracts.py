"""Public contracts work without the separately distributed AIOps engine."""

import importlib.abc
import sys

import pytest


def test_configuration_rejects_core_overrides():
    from veadk.aiops import AgentConfig

    config = AgentConfig(customer_instruction="Customer additions")
    assert config.exploration_seconds == 900
    assert config.invocation_seconds > config.exploration_seconds
    assert config.thinking_mode == "enabled"
    assert not config.sidecar_enabled
    for key in ("system_prompt", "core_prompt", "core_prompt_path"):
        with pytest.raises(ValueError):
            AgentConfig(**{key: "override"})


def test_manifest_resolves_skills_and_preserves_plugin_identity(tmp_path, monkeypatch):
    from veadk.aiops import AgentManifest, AgentPlugin

    (tmp_path / "skills").mkdir()
    (tmp_path / "fixture_plugin.py").write_text(
        "from veadk.aiops import AgentPlugin\n"
        "def build(): return AgentPlugin(name='fixture')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest = tmp_path / "agent.toml"
    manifest.write_text(
        'plugins = ["fixture_plugin:build"]\n'
        'skill_directories = ["skills"]\n'
        '[agent]\nname = "fixture"\ncustomer_instruction = "extra"\n'
    )
    plugins = AgentManifest.load(manifest).load_plugins()
    assert isinstance(plugins[0], AgentPlugin)
    assert plugins[1].skill_directories == (tmp_path / "skills",)


@pytest.mark.parametrize("entry", ["create_agent", "create_app", "create_server"])
def test_hosting_without_engine_has_actionable_error(entry, monkeypatch):
    from veadk.aiops import hosting

    class NoEngine(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "agentkit_aiops":
                raise ModuleNotFoundError("engine absent", name=fullname)

    for name in tuple(sys.modules):
        if name == "agentkit_aiops" or name.startswith("agentkit_aiops."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [NoEngine(), *sys.meta_path])
    with pytest.raises(RuntimeError, match="separately installed binary runtime"):
        getattr(hosting, entry)()


def test_hosting_preserves_dependency_failure(monkeypatch):
    from veadk.aiops import hosting

    def missing_dependency(module):
        raise ModuleNotFoundError("missing dependency", name="engine_dependency")

    monkeypatch.setattr(hosting, "import_module", missing_dependency)
    with pytest.raises(ModuleNotFoundError) as caught:
        hosting.create_agent()
    assert caught.value.name == "engine_dependency"
