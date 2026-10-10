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

"""Verify both native archives in an explicit legacy Studio transport bundle.

Historical updaters authenticate a CLI archive pinned to their own release.
That archive remains intact at the historical path. The target runtime is
separately authenticated against the installed VeADK release's CLI pin and is
the only executable selected at startup. Ordinary bundles keep their contract.
"""

from __future__ import annotations

import hashlib
import gzip
import json
import re
import subprocess
import tempfile
from pathlib import Path


LEGACY_CLI_SHA256 = {
    "0.52.14": "4e76e32c60473b5037c331a7c74bb99b1c23b62eb8ce26379d3a8c41af38a64e",
    "0.52.19": "8cc62477c582a7b9c3f460d2558bed45ee4c81c0169eabc228ddb19387268473",
    "0.52.18": "4439d14b4be6ccb90f6eea896adf959ffef4ab4983f41e449d80c79d4cd95de3",
}
LEGACY_BUNDLE_DESCRIPTOR = "studio-legacy-bundle.json"
TARGET_CLI_DIRECTORY = "studio-cli"
_ARCHIVE_NAME = "agentkit-linux-x64.tar.gz"
_ERROR = "Studio legacy bundle CLI contract is invalid."


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_ERROR)
        result[key] = value
    return result


def resolve_legacy_bundle_archive(
    archive: Path, *, expected_sha256: str, cache_root: Path | None = None
) -> Path:
    """Return a verified target archive; never infer compatibility from failure."""
    descriptor = archive.parent / LEGACY_BUNDLE_DESCRIPTOR
    if not descriptor.exists() and not descriptor.is_symlink():
        return archive
    target = archive.parent / TARGET_CLI_DIRECTORY / _ARCHIVE_NAME
    try:
        if (
            archive.name != _ARCHIVE_NAME
            or any(
                path.is_symlink()
                for path in (archive, descriptor, target.parent, target)
            )
            or not archive.is_file()
            or not descriptor.is_file()
            or descriptor.stat().st_size > 4096
        ):
            raise ValueError(_ERROR)
        contract = json.loads(descriptor.read_bytes(), object_pairs_hook=_unique_object)
        common = {
            "formatVersion",
            "legacyCliVersion",
            "targetCliSha256",
        }
        delta_fields = {
            "deltaSha256",
            "targetTarSha256",
            "targetTarSize",
            "targetCliSize",
        }
        if not isinstance(contract, dict) or (
            set(contract) != common
            if contract.get("formatVersion") == 1
            else set(contract) != common | delta_fields
        ):
            raise ValueError(_ERROR)
        legacy_version = contract["legacyCliVersion"]
        if (
            type(contract["formatVersion"]) is not int
            or contract["formatVersion"] not in {1, 2}
            or not isinstance(legacy_version, str)
            or legacy_version not in LEGACY_CLI_SHA256
            or contract["targetCliSha256"] != expected_sha256
            or _sha256(archive) != LEGACY_CLI_SHA256[legacy_version]
        ):
            raise ValueError(_ERROR)
        if contract["formatVersion"] == 2:
            return _restore_target(archive, contract, cache_root=cache_root)
        if not target.is_file() or _sha256(target) != expected_sha256:
            raise ValueError(_ERROR)
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(_ERROR) from error
    return target


def _restore_target(archive: Path, contract: dict, *, cache_root: Path | None) -> Path:
    from veadk.cli.agentkit_cli import _exclusive_lock, default_agentkit_cli_cache_root
    from veadk.cli.studio_cli_delta import (
        MAX_CLI_ARCHIVE_BYTES,
        MAX_CLI_TAR_BYTES,
        restore_cli_archive,
    )

    delta = archive.parent / TARGET_CLI_DIRECTORY / "agentkit-tar.bsdiff"
    if (
        delta.is_symlink()
        or not delta.is_file()
        or delta.stat().st_size > MAX_CLI_ARCHIVE_BYTES
        or not all(
            isinstance(contract[k], str) and re.fullmatch(r"[a-f0-9]{64}", contract[k])
            for k in ("deltaSha256", "targetTarSha256", "targetCliSha256")
        )
        or type(contract["targetTarSize"]) is not int
        or not 0 < contract["targetTarSize"] <= MAX_CLI_TAR_BYTES
        or type(contract["targetCliSize"]) is not int
        or not 0 < contract["targetCliSize"] <= MAX_CLI_ARCHIVE_BYTES
        or _sha256(delta) != contract["deltaSha256"]
    ):
        raise ValueError(_ERROR)
    root = (
        (cache_root or default_agentkit_cli_cache_root())
        / "legacy-bundles"
        / contract["targetCliSha256"]
    )
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError(_ERROR)
    root.mkdir(parents=True, exist_ok=True)
    target = root / _ARCHIVE_NAME
    lock = root / ".restore.lock"
    if lock.is_symlink() or target.is_symlink():
        raise ValueError(_ERROR)
    with _exclusive_lock(lock):
        if (
            target.is_file()
            and target.stat().st_size == contract["targetCliSize"]
            and _sha256(target) == contract["targetCliSha256"]
        ):
            return target
        # The original gzip is already authenticated against a known old pin.
        with gzip.open(archive, "rb") as stream:
            original = stream.read(MAX_CLI_TAR_BYTES + 1)
        restored = restore_cli_archive(
            original,
            delta.read_bytes(),
            target_size=contract["targetTarSize"],
            max_bytes=MAX_CLI_TAR_BYTES,
        )
        del original
        if hashlib.sha256(restored).hexdigest() != contract["targetTarSha256"]:
            raise ValueError(_ERROR)
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=root) as tmp:
            candidate = Path(tmp) / _ARCHIVE_NAME
            try:
                with candidate.open("wb") as output:
                    subprocess.run(
                        ["gzip", "-n", "-6", "-c"],
                        input=restored,
                        stdout=output,
                        stderr=subprocess.DEVNULL,
                        timeout=120,
                        check=True,
                    )
            except (OSError, subprocess.SubprocessError) as error:
                raise ValueError(_ERROR) from error
            if (
                candidate.stat().st_size != contract["targetCliSize"]
                or _sha256(candidate) != contract["targetCliSha256"]
            ):
                raise ValueError(_ERROR)
            candidate.chmod(0o644)
            candidate.replace(target)
    return target
