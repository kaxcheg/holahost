"""The registry check CI runs — the startup's own, without the environment or the keys."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests._support.registry import registry_data

from scripts.validate_registry import main


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _anthropic_only() -> dict[str, Any]:
    data = registry_data()
    del data["providers"]["other-vendor"]  # no adapter exists for it
    data["aliases"]["fast"] = data["aliases"]["fast"][:1]
    return data


def test_the_shipped_registry_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "registry is valid" in capsys.readouterr().out


def test_a_valid_file_passes_with_no_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No provider key, no database, no settings: CI holds none of them.
    for variable in list(os.environ):
        monkeypatch.delenv(variable)
    assert main([str(_write(tmp_path, _anthropic_only()))]) == 0


def test_a_registry_without_the_smoke_alias_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The rollout's paid smoke calls `fast`; without it every rollout would fail after the swap.
    data = _anthropic_only()
    data["aliases"]["quick"] = data["aliases"].pop("fast")

    assert main([str(_write(tmp_path, data))]) == 1
    assert "'fast'" in capsys.readouterr().err


def test_a_smoke_alias_whose_providers_are_disabled_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = registry_data()
    data["providers"]["other-vendor"]["enabled"] = False
    data["aliases"]["fast"] = data["aliases"]["fast"][1:]

    assert main([str(_write(tmp_path, data))]) == 1
    assert "'fast'" in capsys.readouterr().err


def test_a_file_rule_fails_with_its_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _anthropic_only()
    data["aliases"]["fast"] = [{"provider": "anthropic", "model": "no-such-model"}]

    assert main([str(_write(tmp_path, data))]) == 1
    assert "no-such-model" in capsys.readouterr().err


def test_a_provider_without_an_adapter_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A rule `read_registry` alone never reaches: it belongs to building the repository.
    assert main([str(_write(tmp_path, registry_data()))]) == 1
    assert "no adapter" in capsys.readouterr().err


def test_a_model_too_slow_for_one_attempt_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _anthropic_only()
    data["providers"]["anthropic"]["models"]["claude-haiku-4-5"]["tokens_per_second"] = 1

    assert main([str(_write(tmp_path, data))]) == 1
    err = capsys.readouterr().err
    assert "cannot deliver the answer ceiling" in err
    assert "anthropic/claude-haiku-4-5" in err
