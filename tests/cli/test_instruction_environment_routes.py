"""Exercise real Studio role/ownership checks and the AgentKit update payload."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from tests.cli.test_studio_rbac import (
    _create_studio_app,
    _runtime,
    _runtime_with_public_endpoint,
    _RuntimeJsonResponse,
)


def test_instruction_publication_uses_management_policy_and_exact_update(
    monkeypatch, tmp_path
):
    from agentkit.sdk.runtime.client import AgentkitRuntimeClient

    runtime = _runtime_with_public_endpoint(_runtime("selected-runtime", "developer"))
    runtime.current_version_number = 8
    runtime.status = "Ready"
    runtime.envs = [
        SimpleNamespace(key="OTHER_CONFIGURATION", value="offline-only-value")
    ]
    reads, updates = [], []

    def get_runtime(self, request):
        reads.append(request.runtime_id)
        assert request.runtime_id == "selected-runtime"
        return runtime

    def update_runtime(self, request):
        updates.append(request.model_dump(by_alias=True, exclude_none=True))
        return SimpleNamespace(runtime_id="selected-runtime")

    class OfflineRuntime:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, **kwargs):
            assert method == "GET"
            assert url == "https://runtime.example.com/web/aiops-extension/expert"
            return _RuntimeJsonResponse(
                {
                    "instruction": "initial",
                    "revision": 0,
                    "core_locked": True,
                    "core_position": "first",
                    "runtime_env_supported": True,
                    "runtime_env_empty_safe": True,
                }
            )

    monkeypatch.setattr(AgentkitRuntimeClient, "get_runtime", get_runtime)
    monkeypatch.setattr(AgentkitRuntimeClient, "update_runtime", update_runtime)
    monkeypatch.setattr("httpx.AsyncClient", OfflineRuntime)
    app = _create_studio_app(monkeypatch, tmp_path, developers="developer,other")
    path = "/web/runtime-instruction/selected-runtime/expert?region=cn-beijing"
    with TestClient(app) as client:
        viewer = client.put(
            path,
            headers={"X-VeADK-Local-User": "viewer"},
            json={"instruction": "new", "revision": 8},
        )
        assert viewer.status_code == 403
        assert not reads and not updates
        other = client.put(
            path,
            headers={"X-VeADK-Local-User": "other"},
            json={"instruction": "new", "revision": 8},
        )
        assert other.status_code == 404
        assert not updates
        developer = {"X-VeADK-Local-User": "developer"}
        info = client.get(path, headers=developer)
        assert info.status_code == 200
        assert info.json()["revision"] == 8
        result = client.put(
            path, headers=developer, json={"instruction": "新增要求", "revision": 8}
        )
        assert result.status_code == 200
        assert result.json()["publication"] == "pending"
    assert updates == [
        {
            "RuntimeId": "selected-runtime",
            "ReleaseEnable": True,
            "Envs": [
                {"Key": "OTHER_CONFIGURATION", "Value": "offline-only-value"},
                {"Key": "AIOPS_CUSTOMER_INSTRUCTION", "Value": "新增要求"},
                {"Key": "AIOPS_INSTRUCTION_STORAGE", "Value": "runtime_env"},
            ],
        }
    ]
