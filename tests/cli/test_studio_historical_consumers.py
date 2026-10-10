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

"""Offline regression against byte-identical, provenance-checked old consumers.

The mandatory release job supplies genuine CLI archives in STUDIO_HISTORY_CLI_DIR.
These tests stop at local package preparation; installation and cloud release
remain separate acceptance gates. No credentials or network are used here.
"""

import hashlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import zipfile

import pytest

import frontend.service.studio_release_server as server_package
from frontend.service.studio_release_server import publisher
from veadk.cli.studio_legacy_bundle import LEGACY_CLI_SHA256
from veadk.cli.studio_release import StudioReleaseManifest


PROFILES = ("0.52.14-full", "0.52.14-thin", "0.52.18", "0.52.19")


@pytest.fixture(autouse=True)
def _cleanup_native_packages(tmp_path):
    yield
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture(scope="module")
def archives():
    root = os.getenv("STUDIO_HISTORY_CLI_DIR")
    if not root:
        pytest.skip("Release gate supplies STUDIO_HISTORY_CLI_DIR; no network in tests")
    result = {}
    for version, expected in LEGACY_CLI_SHA256.items():
        path = Path(root) / version / "agentkit-linux-x64.tar.gz"
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected
        result[version] = path.resolve()
    return result


@pytest.fixture(scope="module")
def history(tmp_path_factory):
    root = tmp_path_factory.mktemp("historical_consumers")
    fixture = Path(__file__).parent / "fixtures/studio_updater_history.zip"
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(root)
    sources = json.loads((root / "sources.json").read_text())
    assert len(sources) == 20
    assert {item["profile"] for item in sources} == set(PROFILES)
    for item in sources:
        content = (root / item["profile"] / item["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
    return root


def _load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _consumer(root, profile, monkeypatch):
    name = "_historic_" + profile.replace(".", "_").replace("-", "_")
    directory = root / profile
    package = ModuleType(name)
    package.__path__ = [str(directory / "frontend/service/studio_release_server")]
    monkeypatch.setitem(sys.modules, name, package)
    old_pub = _load(
        name + ".publisher", Path(package.__path__[0]) / "publisher.py", monkeypatch
    )
    old = _load(
        name + "_updater", directory / "veadk/cli/studio_self_update.py", monkeypatch
    )
    reader = _load(
        name + "_reader", directory / "veadk/cli/studio_release.py", monkeypatch
    )
    scripts = _load(
        name + "_package", directory / "veadk/cli/studio_package.py", monkeypatch
    )
    monkeypatch.setattr(old, "studio_run_script", scripts.studio_run_script)
    monkeypatch.setitem(
        sys.modules, "frontend.service.studio_release_server.publisher", old_pub
    )
    monkeypatch.setattr(server_package, "publisher", old_pub)
    return old, reader


def _full_package(root, archive):
    root.mkdir()
    wheel = root / "veadk_python-1.2.3-py3-none-any.whl"
    from veadk.cli import agentkit_cli

    with zipfile.ZipFile(wheel, "w") as bundle:
        bundle.writestr(
            "veadk_python-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: veadk-python\nVersion: 1.2.3\n",
        )
        bundle.writestr(
            "veadk/cli/agentkit_cli.py", Path(agentkit_cli.__file__).read_bytes()
        )
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (root / "requirements.txt").write_text(
        f"--no-index\n--require-hashes\n./{wheel.name} --hash=sha256:{digest}\n"
    )
    (root / "run.sh").write_text("#!/bin/bash\n")
    (root / "agentkit-linux-x64.tar.gz").write_bytes(archive.read_bytes())
    return root


def _zip(root):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root))
    return output.getvalue()


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("transport", ["full", "delta"])
@pytest.mark.parametrize(
    "provider,region", [("volcengine", "cn-shanghai"), ("byteplus", "ap-southeast-1")]
)
def test_real_old_consumers_reject_different_pin_then_accept_matching_envelope(
    history, archives, tmp_path, monkeypatch, profile, provider, region, transport
):
    legacy = profile.split("-")[0]
    target_delta = None
    if transport == "delta":
        if sys.platform != "linux" or legacy != "0.52.14":
            pytest.skip("Pinned .14 delta reconstruction is a Linux release gate")
        target_delta = (
            Path(__file__).parent / "fixtures/cli-tar-0.52.14-to-0.52.19.bsdiff"
        )
        assert (
            hashlib.sha256(target_delta.read_bytes()).hexdigest()
            == "8484054c77ee2fdbdb73e6fe07a293a5ed0b05ad3fce781cb4a7d1b78c3971d7"
        )
    package = _full_package(tmp_path / "package", archives["0.52.19"])
    original_wheel = next(package.glob("*.whl")).read_bytes()
    plain = _zip(package)
    publisher.stage_legacy_studio_bundle(
        package,
        legacy_cli_version=legacy,
        legacy_archive=archives[legacy],
        target_delta=target_delta,
    )
    assert next(package.glob("*.whl")).read_bytes() == original_wheel
    compat = _zip(package)
    old, reader = _consumer(history, profile, monkeypatch)
    updater = old.StudioSelfUpdater(
        settings=old.StudioUpdateSettings(
            bucket="offline-fixture",
            deployment_region=region,
            prefix="veadk/studio/main",
            application_id="offline-app",
            function_id="offline-function",
            project="default",
            provider=provider,
        ),
        credential_resolver=lambda: (
            "offline-placeholder",
            "offline-placeholder",
            None,
        ),
        branding_logo=None,
    )
    for label, content in (("plain", plain), ("compat", compat)):
        release = StudioReleaseManifest(
            version="20260918000000",
            git_sha="a" * 40,
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            created_at="2026-09-18T00:00:00+08:00",
        )
        requests = []

        def get_object(**kwargs):
            requests.append(kwargs["key"])
            return iter([content])

        clients = []

        def tos_client(*_args, **kwargs):
            clients.append(kwargs)
            return SimpleNamespace(get_object=get_object)

        monkeypatch.setitem(sys.modules, "tos", SimpleNamespace(TosClientV2=tos_client))
        store = reader.StudioReleaseStore(
            bucket="offline-fixture",
            region=region,
            provider=provider,
            access_key="offline-placeholder",
            secret_key="offline-placeholder",
        )
        domain = "bytepluses.com" if provider == "byteplus" else "volces.com"
        assert clients == [
            {
                "security_token": None,
                "endpoint": f"tos-{region}.{domain}",
                "region": region,
            }
        ]
        workspace = tmp_path / label
        workspace.mkdir()
        # Full-only releases use the same exact extraction path in every old
        # consumer; later versions expose it through _download_runtime_package.
        if label == "plain" and legacy != "0.52.19":
            archive = workspace / "studio-bundle.zip"
            store.download_bundle(release, archive)
            with pytest.raises(ValueError, match="checksum"):
                old.extract_studio_bundle(archive, workspace / "unpacked")
        else:
            archive = workspace / "studio-bundle.zip"
            store.download_bundle(release, archive)
            unpacked = workspace / "unpacked"
            old.extract_studio_bundle(archive, unpacked)
            updater._prepare_package(unpacked)
            script = (unpacked / "run.sh").read_text()
            assert "veadk.cli.studio_companion" in script
            assert "agentkit-linux-x64.tar.gz" in script
            assert f"--provider {provider}" in script
            assert (
                hashlib.sha256(
                    (unpacked / "agentkit-linux-x64.tar.gz").read_bytes()
                ).hexdigest()
                == LEGACY_CLI_SHA256[legacy]
            )
            if label == "compat":
                if transport == "full":
                    assert (
                        unpacked / "studio-cli/agentkit-linux-x64.tar.gz"
                    ).read_bytes() == archives["0.52.19"].read_bytes()
                else:
                    assert not (
                        unpacked / "studio-cli/agentkit-linux-x64.tar.gz"
                    ).exists()
                    assert target_delta is not None
                    assert (
                        unpacked / "studio-cli/agentkit-tar.bsdiff"
                    ).read_bytes() == target_delta.read_bytes()
        assert len(requests) == 1
        assert updater._settings.provider == provider
        assert updater._settings.deployment_region == region


def test_guided_cli019_badcase_and_existing_cli014_upgrade(
    history, archives, tmp_path, monkeypatch
):
    """Real deployed checker: preserve the normal .14 route, add a .19 bridge.

    The release label alone does not establish an installed CLI contract.
    These fingerprints were checked against the deployed 20260917223852 code.
    """
    fingerprints = {
        "frontend/service/studio_release_server/publisher.py": "7b226918a0b637c8969eea1c0e5b737a96343dd8ff5cf279628c97ed17f193ba",
        "veadk/cli/studio_self_update.py": "0c38712b938f4d75372512a766b3a3e9828c84efd803ae34f9b1ed3fd6359247",
        "veadk/cli/studio_release.py": "189b2cb7753675e4eeccf20c606d91f581bef6842b932c1bc0f03b8c5004d989",
    }
    for name, expected in fingerprints.items():
        assert (
            hashlib.sha256((history / "0.52.19" / name).read_bytes()).hexdigest()
            == expected
        )
    monkeypatch.setenv("VEADK_AGENTKIT_CLI_CACHE", str(tmp_path / "cli-cache"))
    # The ordinary transport and target runtime stay paired using the existing
    # envelope protocol. The full-envelope form keeps this test platform neutral.
    package = _full_package(tmp_path / "package", archives["0.52.19"])
    bridge = tmp_path / "bridge.zip"
    bridge.write_bytes(_zip(package))
    publisher.stage_legacy_studio_bundle(
        package, legacy_cli_version="0.52.14", legacy_archive=archives["0.52.14"]
    )
    normal = tmp_path / "normal.zip"
    normal.write_bytes(_zip(package))
    with monkeypatch.context() as old_context:
        old, _ = _consumer(history, "0.52.19", old_context)
        # RED: exact customer failure, before any code or function submission.
        with pytest.raises(
            ValueError, match="AgentKit CLI archive checksum is invalid"
        ):
            old.extract_studio_bundle(normal, tmp_path / "rejected")
        # GREEN: unchanged old checker accepts the separately selected bridge.
        old.extract_studio_bundle(bridge, tmp_path / "accepted")
        assert (
            tmp_path / "accepted/agentkit-linux-x64.tar.gz"
        ).read_bytes() == archives["0.52.19"].read_bytes()
    for profile in ("0.52.14-full", "0.52.14-thin"):
        with monkeypatch.context() as old_context:
            old, _ = _consumer(history, profile, old_context)
            destination = tmp_path / profile
            old.extract_studio_bundle(normal, destination)
            assert (destination / "agentkit-linux-x64.tar.gz").read_bytes() == archives[
                "0.52.14"
            ].read_bytes()
    # Once the new updater is installed, the ordinary .14 transport still
    # resolves to its target .19 runtime. This is package validation, not E2E.
    from veadk.cli.studio_self_update import extract_studio_bundle

    destination = tmp_path / "new-updater"
    extract_studio_bundle(normal, destination)
    resolved = publisher.validate_studio_bundle_dependencies(
        destination, use_target_cli_pin=True
    )
    assert resolved.read_bytes() == archives["0.52.19"].read_bytes()
