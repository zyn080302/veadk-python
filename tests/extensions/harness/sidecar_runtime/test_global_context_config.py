import json
import sys

import pytest

from veadk.extensions.harness.sidecar_runtime.sidecar import (
    HarnessSidecarError,
    doctor_harness_sidecar,
    start_harness_sidecar,
)

from veadk.extensions.harness.sidecar_runtime.sidecar_config import (
    HarnessSidecarConfig,
    sidecar_config_to_env,
)


def test_global_context_survives_sdk_env_runtime_roundtrip():
    policy = {
        "mode": "auto",
        "context_window": 256000,
        "output_reserve": 16384,
        "summary_model": "deepseek-v4-flash-ga-260731",
        "summary_context_window": 64000,
        "summary_input_limit": 14000,
    }
    config = HarnessSidecarConfig(profile="ops", model_proxy={"global_context": policy})
    env = sidecar_config_to_env(config)
    restored = HarnessSidecarConfig.from_env(env)
    assert restored.model_proxy.global_context == policy
    assert restored.runtime_payload()["model_proxy"]["global_context"] == policy
    assert json.loads(env["HARNESS_GLOBAL_CONTEXT_JSON"]) == policy


def test_compressor_selection_enables_global_budget_and_empty_queries_stay_valid():
    config = HarnessSidecarConfig(profile="ops")
    assert config.model_proxy.global_context == {"mode": "auto"}
    assert config.mcp_gateway.policy["result_quality"]["empty_is_unhealthy"] is False
    assert config.mcp_gateway.policy["budget"]["max_calls_per_session"] == 0


def test_disabling_compressor_does_not_create_global_compression():
    config = HarnessSidecarConfig(
        profile="default", component_overrides={"compressor": False}
    )
    assert config.model_proxy.global_context is None


@pytest.mark.parametrize("command", ["start", "doctor"])
def test_old_runtime_cannot_silently_ignore_global_context(tmp_path, command):
    runtime = tmp_path / "old_runtime.py"
    runtime.write_text(
        'import json\nprint(json.dumps({"status":"ok","model_proxy":{"running":True}}), flush=True)\n'
    )
    config = HarnessSidecarConfig(
        profile="ops", runtime_command=[sys.executable, str(runtime)]
    )
    env = {"MODEL_AGENT_API_BASE": "http://127.0.0.1:1/v1"}
    original = dict(env)
    with pytest.raises(HarnessSidecarError, match="global_context_v1"):
        if command == "start":
            start_harness_sidecar(config, apply_env=True, environ=env)
        else:
            doctor_harness_sidecar(config, env=env)
    assert env == original


def test_runtime_must_confirm_requested_compression_scope(tmp_path):
    runtime = tmp_path / "wrong_scope.py"
    runtime.write_text(
        'import json\nprint(json.dumps({"status":"ok","model_proxy":{"running":True,"capabilities":["global_context_v1"],"compression_scope":"tool_history"}}), flush=True)\n'
    )
    config = HarnessSidecarConfig(
        profile="ops", runtime_command=[sys.executable, str(runtime)]
    )
    with pytest.raises(HarnessSidecarError, match="global_context_v1"):
        start_harness_sidecar(config, environ={})
