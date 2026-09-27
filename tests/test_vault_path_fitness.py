"""Fitness function: vault writes stay under the configured vault path."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.vault import Vault, VaultConfigError, VaultPathError


def test_writes_stay_under_configured_vault_path(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = outside / "escaped.md"
    stamp = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))

    with pytest.raises(VaultConfigError):
        Vault(vault_root, memory_root=str(outside))
    with pytest.raises(VaultConfigError):
        Vault(vault_root, memory_root="../outside")

    vault = Vault(vault_root)
    with pytest.raises(VaultPathError):
        vault.safe_path("..", "outside", "escaped.md")
    with pytest.raises(VaultPathError):
        vault.safe_path(str(escaped))
    with pytest.raises(VaultPathError):
        vault._atomic_write(escaped, "leaked\n")
    assert not escaped.exists()

    (vault_root / "Daily").symlink_to(outside)
    with pytest.raises(VaultPathError):
        vault.append_daily_note("leak", now=stamp)
    assert list(outside.iterdir()) == []

    result = vault.update_project_state("path-boundary", objective="inside", now=stamp)
    written = (vault.root / result.path).resolve()
    assert written.is_relative_to(vault.root.resolve())
    assert written.is_file()
    assert "inside" in written.read_text(encoding="utf-8")
    assert not escaped.exists()
