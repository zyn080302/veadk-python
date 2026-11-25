"""Build the scoped SDK repair from a verified, previously delivered wheel.

Unchanged payloads, dependency metadata and package data are copied byte for
byte. Only the four authorized Python files, version metadata and RECORD change.
This avoids rebuilding unrelated packaged Studio assets from a source checkout.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
from pathlib import Path
import re
import zipfile

BASELINE_SHA256 = "dc30368e863744aac01330f16f541953cb7e636e00528146a3ad9959abff0088"
VERSION = "1.1.15.dev14+aiopsharness.20261125.thoughtfix1"
CHANGED_FILES = frozenset(
    {
        "veadk/runtime/codex/runtime.py",
        "veadk/runtime/codex/translate.py",
        "veadk/tracing/telemetry/telemetry.py",
        "veadk/tracing/telemetry/attributes/extractors/llm_attributes_extractors.py",
    }
)


def build(baseline: Path, source_root: Path, output_dir: Path) -> Path:
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != BASELINE_SHA256:
        raise ValueError("The baseline wheel does not match the approved artifact")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"veadk_python-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(baseline) as original:
        names = original.namelist()
        old_info = next(
            n.rsplit("/", 1)[0] for n in names if n.endswith(".dist-info/METADATA")
        )
        new_info = f"veadk_python-{VERSION}.dist-info"
        actual_changes = {
            name
            for name in names
            if name.startswith("veadk/")
            and name.endswith(".py")
            and (source_root / name).read_bytes() != original.read(name)
        }
        if actual_changes != CHANGED_FILES:
            raise ValueError(
                "SDK source changes differ from the approved four-file scope"
            )
        rows = []
        temporary = target.with_suffix(".tmp")
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED
            ) as result:
                for name in names:
                    if name == old_info + "/RECORD":
                        continue
                    destination = name.replace(old_info + "/", new_info + "/", 1)
                    data = (
                        (source_root / name).read_bytes()
                        if name in CHANGED_FILES
                        else original.read(name)
                    )
                    if name == old_info + "/METADATA":
                        data, count = re.subn(
                            rb"(?m)^Version: [^\r\n]+",
                            b"Version: " + VERSION.encode(),
                            data,
                        )
                        if count != 1:
                            raise ValueError("Expected one wheel Version field")
                    info = original.getinfo(name)
                    entry = zipfile.ZipInfo(destination, info.date_time)
                    entry.external_attr = info.external_attr
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    result.writestr(entry, data)
                    digest = (
                        base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                        .rstrip(b"=")
                        .decode()
                    )
                    rows.append((destination, "sha256=" + digest, str(len(data))))
                record = new_info + "/RECORD"
                rows.append((record, "", ""))
                buffer = io.StringIO(newline="")
                csv.writer(buffer).writerows(rows)
                result.writestr(record, buffer.getvalue())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    target = build(args.baseline_wheel, args.source_root, args.output_dir)
    print(
        f"Built {target.name}; sha256={hashlib.sha256(target.read_bytes()).hexdigest()}"
    )


if __name__ == "__main__":
    main()
