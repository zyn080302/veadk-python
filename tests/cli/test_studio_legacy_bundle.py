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

"""A legacy transport CLI must never become the target Studio's runtime CLI."""

from dataclasses import replace
import hashlib
import json
import io
import gzip
import subprocess
from pathlib import Path
import zipfile

import pytest

from veadk.cli import agentkit_cli, studio_companion, studio_legacy_bundle
from tests.cli.test_studio_companion import _tar_bytes
from tests.cli.test_studio_update_cli_contract import _bundles, _store, _updater
from frontend.service.studio_release_server import publisher
from veadk.cli.studio_self_update import extract_studio_bundle
from tests.cli.test_studio_cli_delta import _patch


def _package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    artifact = agentkit_cli.agentkit_cli_artifact(system="Linux", machine="x86_64")
    content = _tar_bytes(artifact)
    artifact = replace(artifact, sha256=hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(agentkit_cli, "agentkit_cli_artifact", lambda: artifact)
    monkeypatch.setattr(studio_companion, "agentkit_cli_artifact", lambda: artifact)
    legacy = tmp_path / artifact.filename
    legacy.write_bytes(b"authenticated legacy transport archive")
    monkeypatch.setitem(
        studio_legacy_bundle.LEGACY_CLI_SHA256,
        "0.52.14",
        hashlib.sha256(legacy.read_bytes()).hexdigest(),
    )
    target = tmp_path / "studio-cli" / artifact.filename
    target.parent.mkdir()
    target.write_bytes(content)
    (tmp_path / "studio-legacy-bundle.json").write_text(
        json.dumps(
            {
                "formatVersion": 1,
                "legacyCliVersion": "0.52.14",
                "targetCliSha256": artifact.sha256,
            }
        )
    )
    return legacy, target


def test_legacy_entrypoint_installs_only_target_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy, target = _package(tmp_path, monkeypatch)
    executable = studio_companion.resolve_studio_managed_agentkit_cli(
        archive=legacy, cache_root=tmp_path / "cache"
    )
    assert executable is not None
    assert agentkit_cli.validate_agentkit_cli_executable(executable)
    assert executable.read_bytes().endswith(b"ak 0.52.19'\n")
    assert legacy.read_bytes() == b"authenticated legacy transport archive"
    assert target.is_file()


@pytest.mark.parametrize("damaged", ["legacy", "target", "descriptor", "unknown"])
def test_legacy_bundle_rejects_damage_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damaged: str
) -> None:
    legacy, target = _package(tmp_path, monkeypatch)
    descriptor = tmp_path / "studio-legacy-bundle.json"
    if damaged in {"legacy", "target"}:
        (legacy if damaged == "legacy" else target).write_bytes(b"tampered")
    elif damaged == "descriptor":
        descriptor.write_text("{}")
    else:
        data = json.loads(descriptor.read_text())
        data["legacyCliVersion"] = "unrecognized"
        descriptor.write_text(json.dumps(data))
    with pytest.raises(agentkit_cli.AgentKitCliError, match="legacy"):
        studio_companion.resolve_studio_managed_agentkit_cli(
            archive=legacy, cache_root=tmp_path / "cache"
        )
    assert not (tmp_path / "cache").exists()


def test_legacy_cli_without_descriptor_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy, _ = _package(tmp_path, monkeypatch)
    (tmp_path / "studio-legacy-bundle.json").unlink()
    with pytest.raises(agentkit_cli.AgentKitCliError, match="checksum"):
        studio_companion.resolve_studio_managed_agentkit_cli(
            archive=legacy, cache_root=tmp_path / "cache"
        )
    assert not (tmp_path / "cache").exists()


def test_legacy_bundle_rejects_symlinked_runtime_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy, target = _package(tmp_path, monkeypatch)
    target.parent.rename(tmp_path / "external")
    (tmp_path / "studio-cli").symlink_to(
        tmp_path / "external", target_is_directory=True
    )
    with pytest.raises(agentkit_cli.AgentKitCliError, match="legacy"):
        studio_companion.resolve_studio_managed_agentkit_cli(
            archive=legacy, cache_root=tmp_path / "cache"
        )
    assert not (tmp_path / "cache").exists()


def test_compatibility_install_keeps_normal_future_cli_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = tmp_path / "installed"
    initial.mkdir()
    legacy, _ = _package(initial, monkeypatch)
    assert (
        studio_companion.resolve_studio_managed_agentkit_cli(
            archive=legacy, cache_root=tmp_path / "cache"
        )
        is not None
    )

    # The next ordinary release has a different native pin. Its real reader and
    # extractor must use the target wheel's pin without a legacy descriptor.
    full, thin, release = _bundles(tmp_path)
    updater = _updater()
    settings_before = updater._settings
    monkeypatch.setattr(
        "veadk.cli.studio_self_update.probe_studio_artifact", lambda artifact: None
    )
    for mode in ("full", "thin"):
        workspace = tmp_path / mode
        workspace.mkdir()
        selected = (
            replace(release, runtime_epoch="", thin_sha256="", thin_size=0)
            if mode == "full"
            else release
        )
        installed = updater._download_runtime_package(
            _store(full, thin), selected, workspace
        )
        assert installed.is_dir()
        assert not (installed / "studio-legacy-bundle.json").exists()
        assert updater._settings == settings_before


def test_publisher_wraps_target_without_changing_target_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full, _, _ = _bundles(tmp_path)
    package = tmp_path / "package"
    with zipfile.ZipFile(io.BytesIO(full)) as archive:
        archive.extractall(package)
    wheel = next(package.glob("veadk*.whl"))
    wheel_before = wheel.read_bytes()
    target_before = (package / "agentkit-linux-x64.tar.gz").read_bytes()
    monkeypatch.setattr(
        publisher,
        "_AGENTKIT_CLI_ARCHIVE_SHA256",
        hashlib.sha256(target_before).hexdigest(),
    )
    old = tmp_path / "legacy.tar.gz"
    old.write_bytes(b"known historical bytes")
    monkeypatch.setitem(
        studio_legacy_bundle.LEGACY_CLI_SHA256,
        "0.52.14",
        hashlib.sha256(old.read_bytes()).hexdigest(),
    )
    publisher.stage_legacy_studio_bundle(
        package, legacy_cli_version="0.52.14", legacy_archive=old
    )
    assert wheel.read_bytes() == wheel_before
    assert (package / "agentkit-linux-x64.tar.gz").read_bytes() == old.read_bytes()
    assert (
        package / "studio-cli/agentkit-linux-x64.tar.gz"
    ).read_bytes() == target_before
    assert (
        publisher.validate_studio_bundle_dependencies(package, use_target_cli_pin=True)
        == package / "studio-cli/agentkit-linux-x64.tar.gz"
    )

    bundle = tmp_path / "compat.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for path in package.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package))
    extract_studio_bundle(bundle, tmp_path / "unpacked")


def _delta_package(tmp_path, monkeypatch):
    artifact = agentkit_cli.agentkit_cli_artifact(system="Linux", machine="x86_64")
    target_tar = gzip.decompress(_tar_bytes(artifact))
    target_archive = subprocess.run(
        ["gzip", "-n", "-6", "-c"], input=target_tar, capture_output=True, check=True
    ).stdout
    artifact = replace(artifact, sha256=hashlib.sha256(target_archive).hexdigest())
    monkeypatch.setattr(agentkit_cli, "agentkit_cli_artifact", lambda: artifact)
    monkeypatch.setattr(studio_companion, "agentkit_cli_artifact", lambda: artifact)
    legacy = tmp_path / artifact.filename
    legacy.write_bytes(gzip.compress(b"original transport"))
    monkeypatch.setitem(
        studio_legacy_bundle.LEGACY_CLI_SHA256,
        "0.52.14",
        hashlib.sha256(legacy.read_bytes()).hexdigest(),
    )
    directory = tmp_path / "studio-cli"
    directory.mkdir()
    delta = _patch([(0, len(target_tar), 0)], b"", target_tar, len(target_tar))
    (directory / "agentkit-tar.bsdiff").write_bytes(delta)
    descriptor = {
        "formatVersion": 2,
        "legacyCliVersion": "0.52.14",
        "targetCliSha256": artifact.sha256,
        "targetCliSize": len(target_archive),
        "targetTarSize": len(target_tar),
        "targetTarSha256": hashlib.sha256(target_tar).hexdigest(),
        "deltaSha256": hashlib.sha256(delta).hexdigest(),
    }
    (tmp_path / "studio-legacy-bundle.json").write_text(json.dumps(descriptor))
    return legacy, target_archive, descriptor


def test_delta_restores_exact_archive_once_and_starts_target_cli(tmp_path, monkeypatch):
    legacy, expected, contract = _delta_package(tmp_path, monkeypatch)
    original_run = subprocess.run
    compressions = []

    def run(args, **kwargs):
        if args[0] == "gzip":
            compressions.append(True)
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    for _ in range(2):
        restored = studio_legacy_bundle.resolve_legacy_bundle_archive(
            legacy,
            expected_sha256=contract["targetCliSha256"],
            cache_root=tmp_path / "cache",
        )
        assert restored.read_bytes() == expected
    assert compressions == [True]
    executable = studio_companion.resolve_studio_managed_agentkit_cli(
        archive=legacy, cache_root=tmp_path / "cache"
    )
    assert executable is not None
    assert executable.read_bytes().endswith(b"ak 0.52.19'\n")
    assert compressions == [True]


@pytest.mark.parametrize(
    "damage", ["delta", "tarHash", "targetHash", "size", "symlink"]
)
def test_delta_damage_cannot_install_or_execute_cli(tmp_path, monkeypatch, damage):
    legacy, _, contract = _delta_package(tmp_path, monkeypatch)
    delta = tmp_path / "studio-cli/agentkit-tar.bsdiff"
    if damage == "delta":
        delta.write_bytes(b"bad")
    elif damage == "tarHash":
        contract["targetTarSha256"] = "0" * 64
    elif damage == "targetHash":
        contract["targetCliSha256"] = "0" * 64
    elif damage == "size":
        contract["targetTarSize"] = 1 << 40
    else:
        delta.rename(tmp_path / "external-delta")
        delta.symlink_to(tmp_path / "external-delta")
    (tmp_path / "studio-legacy-bundle.json").write_text(json.dumps(contract))
    with pytest.raises(agentkit_cli.AgentKitCliError, match="legacy"):
        studio_companion.resolve_studio_managed_agentkit_cli(
            archive=legacy, cache_root=tmp_path / "cache"
        )
    assert not list((tmp_path / "cache").glob("**/ak"))
