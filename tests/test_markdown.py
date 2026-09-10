from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.markdown import (
    SECRET_PLACEHOLDER,
    TaskMatchError,
    append_under_heading,
    bullet_list,
    format_frontmatter,
    format_heading_time,
    move_task_bullet,
    parse_open_checkboxes,
    parse_project_state,
    redact_secrets,
    section,
    slugify,
)


def test_slugify_normalizes_project_names() -> None:
    assert slugify("Spring Authorization Server") == "spring-authorization-server"
    assert slugify("  Foo_Bar   Baz!! ") == "foo-bar-baz"
    assert slugify("Café Project") == "cafe-project"


def test_slugify_strips_path_characters() -> None:
    assert slugify("../../etc/passwd") == "etcpasswd"
    assert slugify("My / Project") == "my-project"


def test_slugify_rejects_empty_result() -> None:
    with pytest.raises(ValueError, match="empty slug"):
        slugify("!!!")


def test_empty_sections_are_omitted() -> None:
    assert section("Summary", "") == ""
    assert section("Changes", []) == ""
    assert section("Notes", ["", "  "]) == ""
    assert "Summary" in section("Summary", "Built the installer")


def test_frontmatter_is_deterministic() -> None:
    rendered = format_frontmatter(
        {
            "type": "decision",
            "project": "spring-auth",
            "date": "2026-08-22",
            "status": "accepted",
            "tags": ["architecture", "decision"],
        }
    )
    assert rendered == (
        "---\n"
        "type: decision\n"
        "project: spring-auth\n"
        "date: 2026-08-22\n"
        "status: accepted\n"
        "tags:\n"
        "  - architecture\n"
        "  - decision\n"
        "---"
    )


def test_heading_append_creates_and_reuses_sections() -> None:
    first = append_under_heading("", "First item", heading="Work")
    assert first == "## Work\n\nFirst item\n"
    second = append_under_heading(first, "Second item", heading="Work")
    assert second == "## Work\n\nFirst item\n\nSecond item\n"
    with_meetings = append_under_heading(second, "Standup", heading="Meetings")
    assert "## Meetings\n\nStandup" in with_meetings
    assert with_meetings.index("## Work") < with_meetings.index("## Meetings")


def test_heading_append_without_heading_does_not_overwrite() -> None:
    existing = "# Daily\n\nExisting line\n"
    updated = append_under_heading(existing, "New line")
    assert "Existing line" in updated
    assert updated.endswith("New line\n")


def test_bullet_list_and_secret_redaction() -> None:
    rendered = bullet_list(["safe change", "password=hunter2", ""])
    assert "- safe change" in rendered
    assert "hunter2" not in rendered
    assert SECRET_PLACEHOLDER in rendered
    assert redact_secrets("token: ghp_abcdefghijklmnopqrstuvwxyz1234") == (
        f"token: {SECRET_PLACEHOLDER}"
    )


SAMPLE_PROJECT_STATE = """---
type: project-state
project: spring-auth
updated: 2026-08-22T11:42:00-04:00
---

# Project State

## Objective

Ship consent auto-approval

## Current State

Design complete

## Architecture

- stdio MCP

## Completed

- Wired vault

## In Progress

- Existing claim

## Next Steps

- Add characterization tests for Order Status API
- Document the Automations starter pack [repo::jmjava/Uberorchbot]
- [ ] checkbox-shaped leftover

## Notes

- Keep this
"""


def test_parse_project_state_next_steps_bullets() -> None:
    parsed = parse_project_state(SAMPLE_PROJECT_STATE)
    assert parsed["objective"] == "Ship consent auto-approval"
    assert parsed["current_state"] == "Design complete"
    assert parsed["architecture"] == ["stdio MCP"]
    assert parsed["completed"] == ["Wired vault"]
    assert parsed["in_progress"] == ["Existing claim"]
    assert parsed["next_steps"] == [
        "Add characterization tests for Order Status API",
        "Document the Automations starter pack [repo::jmjava/Uberorchbot]",
        "checkbox-shaped leftover",
    ]
    assert parsed["notes"] == ["Keep this"]
    assert parsed["blocked"] == []


def test_move_next_step_to_in_progress() -> None:
    parsed = parse_project_state(SAMPLE_PROJECT_STATE)
    next_steps, in_progress, matched = move_task_bullet(
        parsed["next_steps"],
        parsed["in_progress"],
        "characterization",
    )
    assert matched == "Add characterization tests for Order Status API"
    assert matched not in next_steps
    assert "Document the Automations starter pack [repo::jmjava/Uberorchbot]" in next_steps
    assert in_progress == ["Existing claim", matched]


def test_move_in_progress_to_completed() -> None:
    parsed = parse_project_state(SAMPLE_PROJECT_STATE)
    in_progress, completed, matched = move_task_bullet(
        parsed["in_progress"],
        parsed["completed"],
        "Existing claim",
    )
    assert matched == "Existing claim"
    assert in_progress == []
    assert completed == ["Wired vault", "Existing claim"]


def test_move_task_accepts_raw_bullet_query() -> None:
    source = ["Add characterization tests for Order Status API"]
    next_steps, in_progress, matched = move_task_bullet(
        source, [], "- Add characterization tests for Order Status API"
    )
    assert matched == source[0]
    assert next_steps == []
    assert in_progress == source


def test_move_task_missing_and_ambiguous() -> None:
    items = ["Add characterization tests", "Add docs"]
    with pytest.raises(TaskMatchError, match="No matching"):
        move_task_bullet(items, [], "missing")
    with pytest.raises(TaskMatchError, match="Ambiguous"):
        move_task_bullet(["Add tests", "Add tests later"], [], "Add")


def test_parse_open_checkboxes_skips_checked_items() -> None:
    text = """# Agent Queue

- [ ] Add characterization tests #agent [repo::jmjava/dogfood-api]
- [x] Already done #agent
- [ ] Personal chore
- not a checkbox
"""
    assert parse_open_checkboxes(text) == [
        "Add characterization tests #agent [repo::jmjava/dogfood-api]",
        "Personal chore",
    ]


def test_heading_time_uses_timezone_name() -> None:
    stamp = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))
    assert format_heading_time(stamp) == "11:42 EDT"
