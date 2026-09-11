from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pytest.yml"


def test_ci_workflow_runs_ruff_and_pytest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ruff check src/ tests/" in text
    assert "pytest tests/" in text
    assert "python-version: \"3.12\"" in text


def test_ci_workflow_can_fail_redact_wipe_and_claim_tests() -> None:
    names = [
        "test_read_note_redacts_password_assignment",
        "test_update_project_state_partial_rewrite_keeps_custom_and_omitted_sections",
        "test_claim_task_rejects_ambiguous_queue_without_writing_state",
    ]
    collected = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "tests").glob("test_*.py")
    )
    for name in names:
        assert f"def {name}" in collected
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pytest tests/" in text
    assert "--ignore" not in text
