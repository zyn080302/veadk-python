"""Publish customer additions as configuration of one authorized Runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

INSTRUCTION_ENV = "AIOPS_CUSTOMER_INSTRUCTION"
STORAGE_ENV = "AIOPS_INSTRUCTION_STORAGE"


class _Edit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instruction: str = Field(max_length=65536)
    revision: int = Field(ge=0)

    @field_validator("instruction")
    @classmethod
    def valid_environment_value(cls, value: str) -> str:
        if "\0" in value or len(value.encode("utf-8")) > 65536:
            raise ValueError("Invalid customer instruction")
        return value


@dataclass
class _Pending:
    version: int
    instruction: str
    publication: str = "pending"


def mount_instruction_environment_routes(
    app: FastAPI,
    *,
    require_editor: Callable[[Request], Any],
    authorize: Callable[[Request, str, str], Any],
    require_editable: Callable[[Any], Any],
    normalize_region: Callable[[str], str],
    read_addition: Callable[[Request, Any, str, str, str], Awaitable[dict[str, Any]]],
    publish: Callable[[str, str, dict[str, str]], None],
) -> None:
    # Serialize this Studio's read/check/update sequence. AgentKit currently has
    # no conditional UpdateRuntime; this is not a cross-host transaction lock.
    lock = asyncio.Lock()
    pending: dict[tuple[str, str], _Pending] = {}

    async def snapshot(request: Request, runtime_id: str, region: str, app_name: str):
        require_editor(request)
        runtime = await asyncio.to_thread(authorize, request, runtime_id, region)
        require_editable(runtime)
        version = getattr(runtime, "current_version_number", None)
        if type(version) is not int or version < 0:
            raise HTTPException(409, "Runtime 版本不可用，请刷新后重试")
        envs = {
            item.key: item.value or "" for item in getattr(runtime, "envs", None) or []
        }
        try:
            addition = await read_addition(
                request, runtime, runtime_id, region, app_name
            )
        except HTTPException as error:
            if error.status_code == 404:
                raise HTTPException(
                    404, "所选 Agent 不存在或尚未支持附加提示"
                ) from None
            raise HTTPException(
                502, "无法读取所选 Agent 的附加提示，请检查 Runtime 状态"
            ) from None
        except Exception:  # noqa: BLE001 - SDK errors may contain credentials.
            raise HTTPException(
                502, "无法读取所选 Agent 的附加提示，请检查 Runtime 状态"
            ) from None
        if (
            addition.get("core_locked") is not True
            or addition.get("core_position") != "first"
            or addition.get("runtime_env_supported") is not True
            or addition.get("runtime_env_empty_safe") is not True
            or not isinstance(addition.get("instruction"), str)
        ):
            raise HTTPException(409, "请先升级所选 Agent，以支持附加提示配置发布")
        publication = (
            "ready" if getattr(runtime, "status", None) == "Ready" else "pending"
        )
        managed = envs.get(STORAGE_ENV) == "runtime_env"
        value = envs.get(INSTRUCTION_ENV, "" if managed else addition["instruction"])
        key = (region, runtime_id)
        operation = pending.get(key)
        if operation is not None:
            if version > operation.version and publication == "ready":
                pending.pop(key)
                if (
                    not managed
                    or envs.get(INSTRUCTION_ENV, "") != operation.instruction
                ):
                    raise HTTPException(
                        409, "Runtime 被其他配置更新，请刷新并核对附加提示"
                    )
            else:
                value, publication = operation.instruction, operation.publication
        return envs, {
            "instruction": value,
            "revision": version,
            "core_locked": True,
            "core_position": "first",
            "storage": "runtime_env",
            "publication": publication,
        }

    route = "/web/runtime-instruction/{runtime_id}/{app_name}"

    @app.get(route)
    async def read(
        request: Request,
        response: Response,
        runtime_id: str,
        app_name: str,
        region: str = "",
    ):
        response.headers["Cache-Control"] = "no-store"
        async with lock:
            try:
                _, result = await snapshot(
                    request, runtime_id, normalize_region(region), app_name
                )
                return result
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 - SDK errors may contain credentials.
                raise HTTPException(
                    502, "读取 Runtime 配置失败，请刷新后重试"
                ) from None

    @app.put(route)
    async def update(
        request: Request,
        response: Response,
        runtime_id: str,
        app_name: str,
        region: str = "",
    ):
        require_editor(request)
        response.headers["Cache-Control"] = "no-store"
        try:
            edit = _Edit.model_validate(await request.json())
        except (ValidationError, ValueError, UnicodeError):
            raise HTTPException(
                422, "附加提示格式无效，UTF-8 内容须不超过 64 KiB"
            ) from None
        region = normalize_region(region)
        async with lock:
            try:
                envs, current = await snapshot(request, runtime_id, region, app_name)
                if (
                    current["publication"] != "ready"
                    or current["revision"] != edit.revision
                ):
                    raise HTTPException(409, "Runtime 已变化或正在发布，请刷新后重试")
                if (
                    envs.get(STORAGE_ENV) == "runtime_env"
                    and envs.get(INSTRUCTION_ENV, "") == edit.instruction
                ):
                    return current
                key = (region, runtime_id)
                # Keep only unresolved submissions. Never retry a possibly
                # accepted mutation solely because its response was lost.
                if len(pending) >= 128:
                    raise HTTPException(409, "请先核对尚未完成的配置发布")
                operation = _Pending(edit.revision, edit.instruction)
                pending[key] = operation
                try:
                    await asyncio.to_thread(
                        publish,
                        runtime_id,
                        region,
                        {
                            **envs,
                            INSTRUCTION_ENV: edit.instruction,
                            STORAGE_ENV: "runtime_env",
                        },
                    )
                except Exception:  # noqa: BLE001 - SDK errors may contain credentials.
                    operation.publication = "unknown"
                    raise HTTPException(
                        502,
                        "配置发布结果尚未确认，请刷新并核对 Runtime 状态，勿重复提交",
                    ) from None
                return {
                    **current,
                    "instruction": edit.instruction,
                    "publication": "pending",
                }
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 - SDK errors may contain credentials.
                raise HTTPException(
                    502, "提交 Runtime 配置失败，请核对发布状态"
                ) from None
