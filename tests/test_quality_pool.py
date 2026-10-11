"""The quality-pool tool returns the process contract and does not touch the vault."""

from __future__ import annotations

from pathlib import Path

from obsidian_dev_memory.quality_pool import quality_pool_flow
from obsidian_dev_memory.server import _SECURITY_INSTRUCTIONS, create_server, list_tool_names
from obsidian_dev_memory.vault import Vault


def test_quality_pool_flow_states_the_workflow_gate() -> None:
    flow = quality_pool_flow()
    assert flow["cap"] == 7
    assert flow["refill_when_seat_exits"] is True
    assert flow["techniques"] == [
        "clean_as_you_code",
        "hotspot",
        "fitness",
        "static_baseline",
        "mutation",
    ]
    workflow = " ".join(flow["workflow"])
    assert "Pending is not a pass" in workflow
    assert "branch protection does not require it" in workflow
    assert "every check in that run is success" in workflow
    assert "exits 0" in workflow
    assert "embabel/guide" in " ".join(flow["stop"])


def test_quality_pool_tool_does_not_write_the_vault(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    vault = Vault(root)
    server = create_server(vault)
    assert "quality_pool_flow" in list_tool_names(server)
    assert "Pending is not a pass" in _SECURITY_INSTRUCTIONS
    assert "quality_pool_flow" in _SECURITY_INSTRUCTIONS
    assert list(root.rglob("*")) == []
