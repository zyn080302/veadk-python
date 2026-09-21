"""Publish only one additive field through the authorized Runtime control plane."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from frontend.server.instruction_environment import mount_instruction_environment_routes


@pytest.fixture
def host():
    app = FastAPI()
    state = SimpleNamespace(
        version=4,
        status="Ready",
        allowed=True,
        editable=True,
        supported=True,
        empty_safe=True,
        failure=False,
        writes=[],
        reads=[],
        envs={"UNCHANGED": "offline-fixture"},
    )

    def require_editor(request):
        if request.headers.get("x-editor") != "yes":
            raise HTTPException(403)

    def authorize(request, runtime_id, region):
        state.reads.append((runtime_id, region))
        if not state.allowed or runtime_id != "selected-runtime":
            raise HTTPException(404)
        return SimpleNamespace(
            current_version_number=state.version,
            status=state.status,
            envs=[SimpleNamespace(key=k, value=v) for k, v in state.envs.items()],
        )

    def require_editable(runtime):
        if not state.editable:
            raise HTTPException(409)

    async def read_addition(request, runtime, runtime_id, region, app_name):
        if app_name != "expert":
            raise HTTPException(404)
        return {
            "instruction": "existing addition",
            "revision": 0,
            "core_locked": True,
            "core_position": "first",
            "runtime_env_supported": state.supported,
            "runtime_env_empty_safe": state.empty_safe,
        }

    def publish(runtime_id, region, envs):
        state.writes.append((runtime_id, region, dict(envs)))
        if state.failure:
            raise RuntimeError("sensitive upstream fixture must not be echoed")
        state.envs = dict(envs)

    mount_instruction_environment_routes(
        app,
        require_editor=require_editor,
        authorize=authorize,
        require_editable=require_editable,
        normalize_region=lambda r: r or "cn-beijing",
        read_addition=read_addition,
        publish=publish,
    )
    with TestClient(app) as client:
        yield state, client


PATH = "/web/runtime-instruction/selected-runtime/expert?region=cn-beijing"
HEADERS = {"x-editor": "yes"}


def test_publish_preserves_envs_and_waits_for_real_version(host):
    state, client = host
    before = client.get(PATH, headers=HEADERS).json()
    assert before["instruction"] == "existing addition"
    assert before["revision"] == 4
    response = client.put(
        PATH, headers=HEADERS, json={"instruction": "客户\n补充", "revision": 4}
    )
    assert response.status_code == 200
    assert response.json()["publication"] == "pending"
    assert state.writes == [
        (
            "selected-runtime",
            "cn-beijing",
            {
                "UNCHANGED": "offline-fixture",
                "AIOPS_CUSTOMER_INSTRUCTION": "客户\n补充",
                "AIOPS_INSTRUCTION_STORAGE": "runtime_env",
            },
        )
    ]
    # Control-plane eventual consistency must not cause a second update.
    repeated = client.put(
        PATH, headers=HEADERS, json={"instruction": "again", "revision": 4}
    )
    assert repeated.status_code == 409
    assert len(state.writes) == 1
    assert client.get(PATH, headers=HEADERS).json()["publication"] == "pending"
    state.version = 5
    after = client.get(PATH, headers=HEADERS).json()
    assert after["publication"] == "ready"
    assert after["instruction"] == "客户\n补充"
    assert after["revision"] == 5
    assert (
        client.put(
            PATH, headers=HEADERS, json={"instruction": "", "revision": 5}
        ).status_code
        == 200
    )
    assert state.envs["AIOPS_CUSTOMER_INSTRUCTION"] == ""
    assert state.envs["UNCHANGED"] == "offline-fixture"


@pytest.mark.parametrize(
    "condition", ["role", "owner", "review", "version", "busy", "old-core", "wrong-app"]
)
def test_rejects_invalid_target_or_stale_edit_without_writes(host, condition):
    state, client = host
    headers = HEADERS if condition != "role" else {}
    state.allowed = condition != "owner"
    state.editable = condition != "review"
    state.supported = condition != "old-core"
    if condition == "busy":
        state.status = "Updating"
    path = PATH.replace("/expert?", "/other?") if condition == "wrong-app" else PATH
    response = client.put(
        path,
        headers=headers,
        json={"instruction": "new", "revision": 3 if condition == "version" else 4},
    )
    assert response.status_code in {403, 404, 409}
    assert not state.writes
    if condition == "role":
        assert not state.reads


def test_failed_submission_is_not_replayed_or_leaked(host):
    state, client = host
    state.failure = True
    response = client.put(
        PATH, headers=HEADERS, json={"instruction": "new", "revision": 4}
    )
    assert response.status_code == 502
    assert "sensitive upstream" not in response.text
    assert client.get(PATH, headers=HEADERS).json()["publication"] == "unknown"
    assert (
        client.put(
            PATH, headers=HEADERS, json={"instruction": "new", "revision": 4}
        ).status_code
        == 409
    )
    assert len(state.writes) == 1


@pytest.mark.parametrize(
    "edit",
    [
        {"instruction": "new", "revision": True},
        {"instruction": "new", "revision": 4, "core_instruction": "replacement"},
        {"instruction": "nul\x00value", "revision": 4},
    ],
)
def test_validation_rejects_invalid_edits_without_echo(host, edit):
    state, client = host
    response = client.put(PATH, headers=HEADERS, json=edit)
    assert response.status_code == 422
    assert "replacement" not in response.text
    assert not state.writes


def test_empty_instruction_migrates_storage_and_survives_omitted_empty_key(host):
    state, client = host
    state.envs["AIOPS_CUSTOMER_INSTRUCTION"] = ""
    response = client.put(
        PATH, headers=HEADERS, json={"instruction": "", "revision": 4}
    )
    assert response.status_code == 200
    assert len(state.writes) == 1
    assert state.envs["AIOPS_INSTRUCTION_STORAGE"] == "runtime_env"
    # Some hosting layers omit empty values when constructing process envs.
    state.envs.pop("AIOPS_CUSTOMER_INSTRUCTION")
    state.version = 5
    result = client.get(PATH, headers=HEADERS)
    assert result.status_code == 200
    assert result.json()["publication"] == "ready"
    assert result.json()["instruction"] == ""
    repeated = client.put(
        PATH, headers=HEADERS, json={"instruction": "", "revision": 5}
    )
    assert repeated.status_code == 200
    assert len(state.writes) == 1


def test_core_without_explicit_empty_support_cannot_publish(host):
    state, client = host
    state.empty_safe = False
    response = client.put(
        PATH, headers=HEADERS, json={"instruction": "", "revision": 4}
    )
    assert response.status_code == 409
    assert not state.writes
