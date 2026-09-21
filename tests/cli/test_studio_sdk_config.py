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

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from agentkit.toolkit.config import AgentkitConfigManager

from veadk.cli.studio_sdk_config import sdk_build_config, sdk_memory_config


def _config():
    return {
        "common": {
            "agent_name": "offline-agent",
            "entry_point": "app.py",
            "launch_type": "cloud",
            "python_version": "3.12",
            "runtime_envs": {"CUSTOM": "synthetic-common-value"},
        },
        "launch_types": {
            "cloud": {
                "runtime_envs": {"CUSTOM": "synthetic-runtime-value"},
                "runtime_apikey": "synthetic-auth-value",
                "runtime_id": "offline-runtime",
            }
        },
    }


def test_real_sdk_writeback_keeps_environment_private_and_preserves_build_result(
    tmp_path: Path,
) -> None:
    config = _config()
    original = deepcopy(config)
    path = tmp_path / "agentkit.yaml"
    path.write_text(yaml.safe_dump(sdk_build_config(config)))
    baseline = path.read_bytes()

    with sdk_memory_config(path, config):
        build = AgentkitConfigManager.from_dict(config, base_config_path=path)
        build.update_strategy_config(
            "cloud", {"cr_image_full_url": "example.invalid/offline:candidate"}
        )
        # Match sdk.launch: the deploy executor loads a fresh config manager.
        deploy = AgentkitConfigManager.from_dict(config, base_config_path=path)
        deployed = deploy.get_strategy_config("cloud")
        assert deployed["cr_image_full_url"] == "example.invalid/offline:candidate"
        assert deployed["runtime_id"] == "offline-runtime"
        assert (
            deployed["runtime_envs"]
            == original["launch_types"]["cloud"]["runtime_envs"]
        )
        assert deployed["runtime_apikey"] == "synthetic-auth-value"
        deploy.update_strategy_config(
            "cloud", {"runtime_apikey": "synthetic-generated-value"}
        )

    assert (
        config["launch_types"]["cloud"]["runtime_apikey"] == "synthetic-generated-value"
    )
    assert path.read_bytes() == baseline
    assert "synthetic-" not in path.read_text()
    assert yaml.safe_load(path.read_text())["launch_types"] == {}


def test_sdk_save_patch_restores_on_failure_and_does_not_touch_other_projects(
    tmp_path: Path,
) -> None:
    config = _config()
    target = tmp_path / "agentkit.yaml"
    target.write_text(yaml.safe_dump(sdk_build_config(config)))
    other = tmp_path / "other.yaml"
    other.write_text("common: {}\nlaunch_types: {}\n")
    original_save = AgentkitConfigManager._save_config
    with pytest.raises(RuntimeError, match="synthetic build failure"):
        with sdk_memory_config(target, config):
            unrelated = AgentkitConfigManager.from_dict(
                {"common": {}, "launch_types": {}}, base_config_path=other
            )
            unrelated.update_strategy_config("cloud", {"runtime_id": "other-runtime"})
            assert yaml.safe_load(other.read_text())["launch_types"]["cloud"] == {
                "runtime_id": "other-runtime"
            }
            raise RuntimeError("synthetic build failure")
    assert AgentkitConfigManager._save_config is original_save
    assert "synthetic-" not in target.read_text()


def test_nested_sdk_launches_keep_each_config_in_memory(tmp_path: Path) -> None:
    outer, inner = _config(), _config()
    outer_path, inner_path = tmp_path / "outer.yaml", tmp_path / "inner.yaml"
    for path in (outer_path, inner_path):
        path.write_text("common: {}\nlaunch_types: {}\n")
    original_save = AgentkitConfigManager._save_config
    with sdk_memory_config(outer_path, outer):
        with sdk_memory_config(inner_path, inner):
            for path, config, image in (
                (outer_path, outer, "example.invalid/outer:candidate"),
                (inner_path, inner, "example.invalid/inner:candidate"),
            ):
                manager = AgentkitConfigManager.from_dict(config, base_config_path=path)
                manager.update_strategy_config("cloud", {"cr_image_full_url": image})
                assert config["launch_types"]["cloud"]["cr_image_full_url"] == image
                assert "synthetic-" not in path.read_text()
    assert AgentkitConfigManager._save_config is original_save


def test_file_only_sdk_launch_keeps_existing_behavior(tmp_path: Path) -> None:
    original_save = AgentkitConfigManager._save_config
    with sdk_memory_config(tmp_path / "agentkit.yaml", None):
        assert AgentkitConfigManager._save_config is original_save


def test_actual_sdk_launch_carries_build_outputs_into_deploy_without_disk_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agentkit.toolkit import sdk
    from agentkit.toolkit.executors.base_executor import BaseExecutor
    from agentkit.toolkit.models import (
        BuildResult,
        ConfigUpdates,
        DeployResult,
        PreflightMode,
    )

    config = _config()
    config["launch_types"]["cloud"].update(
        region="cn-shanghai",
        tos_bucket="offline-build-bucket",
        cr_instance_name="offline-registry",
    )
    path = tmp_path / "agentkit.yaml"
    path.write_text(yaml.safe_dump(sdk_build_config(config)))
    (tmp_path / "app.py").write_text("# Offline build marker\n")
    seen = []

    class Backend:
        def build(self, common, cloud):
            assert cloud.runtime_envs == {"CUSTOM": "synthetic-runtime-value"}
            changes = ConfigUpdates()
            changes.add("cr_image_full_url", "example.invalid/offline:candidate")
            seen.append("build")
            return BuildResult(success=True, config_updates=changes)

        def deploy(self, common, cloud):
            assert cloud.cr_image_full_url == "example.invalid/offline:candidate"
            assert cloud.runtime_envs == {"CUSTOM": "synthetic-runtime-value"}
            assert cloud.runtime_apikey == "synthetic-auth-value"
            assert "synthetic-" not in path.read_text()
            changes = ConfigUpdates()
            changes.add("runtime_apikey", "synthetic-generated-value")
            seen.append("deploy")
            return DeployResult(success=True, config_updates=changes)

    monkeypatch.setattr(BaseExecutor, "_get_strategy", lambda *a, **k: Backend())
    monkeypatch.setattr(
        "agentkit.toolkit.config.global_config.get_global_config",
        lambda: SimpleNamespace(defaults=SimpleNamespace(preflight_mode="skip")),
    )
    with sdk_memory_config(path, config):
        result = sdk.launch(
            config_file=str(path), config_dict=config, preflight_mode=PreflightMode.SKIP
        )
    assert result.success, result.error
    assert seen == ["build", "deploy"]
    assert (
        config["launch_types"]["cloud"]["runtime_apikey"] == "synthetic-generated-value"
    )
    assert "synthetic-" not in path.read_text()
