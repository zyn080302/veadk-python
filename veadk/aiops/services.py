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

"""Host service facade for reviewed domain adapters.

These functions execute in the trusted host. They contain no investigation
logic and do not download or distribute the private engine.
"""

from .hosting import _resolve


async def run_mcp_with_inquiry_deadline(*args, **kwargs):
    return await _resolve(
        "agentkit_aiops.runtime.agentkit_app_compat", "run_mcp_with_inquiry_deadline"
    )(*args, **kwargs)


def classify_evidence_response(*args, **kwargs):
    return _resolve(
        "agentkit_aiops.runtime.parallel_evidence", "classify_evidence_response"
    )(*args, **kwargs)


def with_evidence_receipt(*args, **kwargs):
    return _resolve(
        "agentkit_aiops.runtime.parallel_evidence", "with_evidence_receipt"
    )(*args, **kwargs)


def capture_provider_call(*args, **kwargs):
    return _resolve("agentkit_aiops.runtime.provider_capture", "capture_provider_call")(
        *args, **kwargs
    )


def runtime_invocation_headers(*args, **kwargs):
    return _resolve(
        "agentkit_aiops.runtime.provider_capture", "runtime_invocation_headers"
    )(*args, **kwargs)


def project_visible_text(*args, **kwargs):
    return _resolve("agentkit_aiops.runtime.reasoning_text", "project_visible_text")(
        *args, **kwargs
    )


__all__ = [
    "run_mcp_with_inquiry_deadline",
    "classify_evidence_response",
    "with_evidence_receipt",
    "capture_provider_call",
    "runtime_invocation_headers",
    "project_visible_text",
]
