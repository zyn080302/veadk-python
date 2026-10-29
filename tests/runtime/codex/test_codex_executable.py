"""Deployment executable selection never comes from serialized agent input."""

from pathlib import Path

import pytest

from veadk.runtime.codex.config import CodexRuntimeConfig
from veadk.runtime.codex.config import configured_codex_binary


def test_missing_override_preserves_sdk_default(monkeypatch):
    monkeypatch.delenv("VEADK_CODEX_BIN", raising=False)
    assert configured_codex_binary() is None


@pytest.mark.parametrize("invalid", ["", "codex", "./codex", "~/bin/codex"])
def test_invalid_override_fails_without_disclosing_path(monkeypatch, invalid):
    monkeypatch.setenv("VEADK_CODEX_BIN", invalid)
    with pytest.raises(ValueError) as exc:
        configured_codex_binary()
    assert str(exc.value) == (
        "VEADK_CODEX_BIN must be an absolute path to an executable file"
    )


@pytest.mark.parametrize("kind", ["missing", "directory", "not-executable"])
def test_unusable_file_is_rejected(monkeypatch, tmp_path, kind):
    target = tmp_path / "operator-private-path"
    if kind == "directory":
        target.mkdir()
    elif kind == "not-executable":
        target.write_text("not executable")
        target.chmod(0o600)
    monkeypatch.setenv("VEADK_CODEX_BIN", str(target))
    with pytest.raises(ValueError) as exc:
        configured_codex_binary()
    assert str(target) not in str(exc.value)


def test_shell_characters_remain_one_literal_path(monkeypatch, tmp_path):
    target = tmp_path / "codex ; $(unused)"
    target.write_text("not executed while selecting the path")
    target.chmod(0o700)
    monkeypatch.setenv("VEADK_CODEX_BIN", str(target))
    assert configured_codex_binary() == str(target)


def test_symlink_to_installed_executable_is_supported(monkeypatch, tmp_path):
    target = tmp_path / "codex"
    target.write_text("not executed while selecting the path")
    target.chmod(0o700)
    link = tmp_path / "bin-link"
    link.symlink_to(target)
    monkeypatch.setenv("VEADK_CODEX_BIN", str(link))
    assert Path(configured_codex_binary()) == link


def test_binary_override_is_not_an_editable_agent_field():
    properties = CodexRuntimeConfig.model_json_schema()["properties"]
    assert "codex_bin" not in properties
    assert "VEADK_CODEX_BIN" not in properties
