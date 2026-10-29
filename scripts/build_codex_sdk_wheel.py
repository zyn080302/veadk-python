"""Build a headless SDK artifact without Studio assets or application Core code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def prepare(destination: Path) -> dict[str, str]:
    names = (
        subprocess.check_output(["git", "ls-files", "-z", "veadk"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    hashes = {}
    for name in names:
        if not name or name.startswith(
            ("veadk/webui/", "veadk/realtime/", "veadk/integrations/mpa/managed/")
        ):
            continue
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("SDK input must be a regular tracked file")
        data = source.read_bytes()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    project = (ROOT / "pyproject.toml").read_text()
    project, count = re.subn(
        r"\[project.scripts\]\n.*?(?=\n\[)", "", project, flags=re.S
    )
    assert count == 1
    project = project.replace('    "frontend*",\n', "")
    (destination / "pyproject.toml").write_text(project)
    (destination / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
    (destination / "README.md").write_text(
        "# VeADK Codex Runtime SDK\n\n"
        "Python SDK build for headless Agent runtimes. Includes the public "
        "VeADK runtime and provider APIs. Does not include Studio UI, a Studio "
        "server distribution, realtime audio, managed MPA provisioning, "
        "a veadk console entry point, or application Core "
        "implementations. Use official openai-codex 0.163.0 and select the "
        "separately installed Codex CLI 0.164.0 with VEADK_CODEX_BIN.\n"
    )
    return hashes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9A-Za-z.+-]+", args.version):
        parser.error("version must be a package version")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_codex_terminal_integrity.py")],
        cwd=ROOT,
        check=True,
    )
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="veadk-headless-build-") as directory:
        context = Path(directory)
        inputs = prepare(context)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(output),
            ],
            cwd=context,
            env={
                **os.environ,
                "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_VEADK_PYTHON": args.version,
            },
            check=True,
        )
    wheel = output / f"veadk_python-{args.version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            assert name.startswith(
                ("veadk/", f"veadk_python-{args.version}.dist-info/")
            )
            assert not name.startswith("veadk/webui/")
    manifest = {
        "profile": "headless-python-sdk",
        "version": args.version,
        "wheel": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip(),
        "source_files": inputs,
        "pyproject_sha256": hashlib.sha256(
            (ROOT / "pyproject.toml").read_bytes()
        ).hexdigest(),
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
