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
# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
# SPDX-License-Identifier: Apache-2.0
"""A guided package may never replace the ordinary upgrade default."""

from dataclasses import replace
import hashlib
import json

import pytest

from tests.cli.test_studio_release import _FakeTosClient, _manifest, _store
from veadk.cli.studio_release import StudioReleaseError


class ObjectResponse(list):
    def __init__(self, content):
        super().__init__([content])
        self.etag = hashlib.sha256(content).hexdigest()


class ConditionalClient(_FakeTosClient):
    def __init__(self):
        super().__init__()
        self.race = False
        self.timeout_after_write = False

    def get_object(self, *, bucket, key):
        content = self.objects[(bucket, key)]
        return ObjectResponse(content)

    def put_object(self, *, if_match=None, **kwargs):
        key = (kwargs["bucket"], kwargs["key"])
        if if_match is not None:
            if self.race:
                self.objects[key] = self.objects[key] + b"\n"
            if hashlib.sha256(self.objects[key]).hexdigest() != if_match:
                raise RuntimeError("conditional write rejected")
        super().put_object(**kwargs)
        if if_match is not None and self.timeout_after_write:
            raise TimeoutError("response lost after accepted write")


def setup_channel(tmp_path):
    client = ConditionalClient()
    store = _store(client)
    normal = replace(_manifest(), version="20261009160100")
    bundle = tmp_path / "normal.zip"
    bundle.write_bytes(b"bundle")
    store.publish(bundle, normal)
    baseline = dict(client.objects)
    client.put_order.clear()
    guided = replace(normal, version="20261009160000", changelog=("Guided upgrade",))
    return client, store, bundle, normal, guided, baseline


def test_guided_release_preserves_defaults_and_every_existing_object(tmp_path):
    client, store, bundle, normal, guided, baseline = setup_channel(tmp_path)
    store.publish_guided(bundle, guided, source_version="20260917223852")
    for key, value in baseline.items():
        if not key[1].endswith("/releases.json"):
            assert client.objects[key] == value
    assert store.latest_manifest() == normal
    assert store.release_catalog() == [normal, guided]
    assert not any(key.endswith("/latest.json") for key in client.put_order)
    before = list(client.put_order)
    store.publish_guided(bundle, guided, source_version="20260917223852")
    assert client.put_order == before


@pytest.mark.parametrize(
    "version", ["20261009160100", "20261009160200", "20260917223852"]
)
def test_guided_release_cannot_be_default_or_downgrade(tmp_path, version):
    client, store, bundle, _, guided, baseline = setup_channel(tmp_path)
    with pytest.raises(StudioReleaseError):
        store.publish_guided(
            bundle, replace(guided, version=version), source_version="20260917223852"
        )
    assert client.objects == baseline
    assert client.put_order == []


def test_guided_release_conflicting_catalog_does_not_write(tmp_path):
    client, store, bundle, normal, guided, _ = setup_channel(tmp_path)
    key = (store.bucket, store.prefix + "/releases.json")
    client.objects[key] = json.dumps(
        {"releases": [json.loads(replace(normal, sha256="c" * 64).to_json())]}
    ).encode()
    with pytest.raises(StudioReleaseError):
        store.publish_guided(bundle, guided, source_version="20260917223852")
    assert client.put_order == []


def test_guided_release_never_discards_an_existing_version(tmp_path):
    client, store, bundle, normal, guided, _ = setup_channel(tmp_path)
    key = (store.bucket, store.prefix + "/releases.json")
    releases = [normal] + [
        replace(normal, version=f"202609010000{i:02}") for i in range(49)
    ]
    client.objects[key] = json.dumps(
        {"releases": [json.loads(item.to_json()) for item in releases]}
    ).encode()
    with pytest.raises(StudioReleaseError):
        store.publish_guided(bundle, guided, source_version="20260917223852")
    assert client.put_order == []


def test_guided_release_does_not_overwrite_concurrent_catalog_change(tmp_path):
    client, store, bundle, _, guided, baseline = setup_channel(tmp_path)
    client.race = True
    with pytest.raises(StudioReleaseError):
        store.publish_guided(bundle, guided, source_version="20260917223852")
    key = (store.bucket, store.prefix + "/releases.json")
    assert client.objects[key] == baseline[key] + b"\n"
    assert not any(key.endswith("/latest.json") for key in client.put_order)


def test_guided_release_reconciles_timeout_without_repeating_write(tmp_path):
    client, store, bundle, normal, guided, _ = setup_channel(tmp_path)
    client.timeout_after_write = True
    store.publish_guided(bundle, guided, source_version="20260917223852")
    assert store.release_catalog() == [normal, guided]
    assert client.put_order.count(store.prefix + "/releases.json") == 1
