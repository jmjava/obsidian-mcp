from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.markdown import (
    SECRET_PLACEHOLDER,
    TaskMatchError,
    append_under_heading,
    bullet_list,
    find_matching_task,
    find_task_across_sources,
    format_frontmatter,
    format_heading_time,
    move_open_checkbox,
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

## Blockers

- Waiting on review

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
    assert parsed["blocked"] == ["Waiting on review"]


def test_parse_project_state_merges_blocked_and_blockers() -> None:
    markdown = """# Project State

## Next Steps

- Write docs

## Blocked

- Waiting on review
- Add tests

## Blockers

- External dependency
- Add tests later
"""
    parsed = parse_project_state(markdown)
    assert parsed["next_steps"] == ["Write docs"]
    assert parsed["blocked"] == [
        "Waiting on review",
        "Add tests",
        "External dependency",
        "Add tests later",
    ]
    with pytest.raises(TaskMatchError, match="Ambiguous"):
        find_matching_task(parsed["blocked"], "Add")
    with pytest.raises(TaskMatchError, match="No matching"):
        find_matching_task(parsed["blocked"], "Write docs")
    assert find_matching_task(parsed["blocked"], "review") == "Waiting on review"


def test_parse_blockers_keeps_secret_until_redact() -> None:
    parsed = parse_project_state(
        "# Project State\n\n## Blockers\n\n- Rotate password=hunter2\n"
    )
    assert parsed["blocked"] == ["Rotate password=hunter2"]
    assert redact_secrets(parsed["blocked"][0]) == f"Rotate {SECRET_PLACEHOLDER}"
    assert "hunter2" not in redact_secrets(parsed["blocked"][0])


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


def test_move_next_step_or_in_progress_to_blocked() -> None:
    parsed = parse_project_state(SAMPLE_PROJECT_STATE)
    next_match, from_section = find_task_across_sources(
        (("Next Steps", parsed["next_steps"]), ("In Progress", parsed["in_progress"])),
        "characterization",
    )
    next_steps, blocked, moved = move_task_bullet(
        parsed["next_steps"],
        parsed["blocked"],
        "characterization",
    )
    assert from_section == "Next Steps"
    assert next_match == moved == "Add characterization tests for Order Status API"
    assert next_match not in next_steps
    assert blocked == ["Waiting on review", next_match]

    progress_match, from_section = find_task_across_sources(
        (("Next Steps", next_steps), ("In Progress", parsed["in_progress"])),
        "Existing claim",
    )
    in_progress, blocked, moved = move_task_bullet(
        parsed["in_progress"],
        blocked,
        "Existing claim",
    )
    assert from_section == "In Progress"
    assert progress_match == moved == "Existing claim"
    assert in_progress == []
    assert blocked == ["Waiting on review", next_match, "Existing claim"]


def test_find_task_across_sources_missing_and_ambiguous() -> None:
    sources = (
        ("Next Steps", ["Add characterization tests", "Write docs"]),
        ("In Progress", ["Add review notes"]),
    )
    with pytest.raises(TaskMatchError, match="No matching"):
        find_task_across_sources(sources, "missing")
    with pytest.raises(TaskMatchError, match="Ambiguous"):
        find_task_across_sources(sources, "Add")
    with pytest.raises(TaskMatchError, match="task text is required"):
        find_task_across_sources(sources, "   ")


SAMPLE_AGENT_QUEUE = """# Agent Queue

## Inbox

- [ ] Add characterization tests #agent [repo::jmjava/dogfood-api]
- [x] Already done #agent
- [ ] Personal chore
- not a checkbox

## Later

- [ ] Write the Automations starter pack docs
"""


def test_parse_open_checkboxes_skips_checked_items() -> None:
    assert parse_open_checkboxes(SAMPLE_AGENT_QUEUE) == [
        "Add characterization tests #agent [repo::jmjava/dogfood-api]",
        "Personal chore",
        "Write the Automations starter pack docs",
    ]


def test_move_open_checkbox_checks_only_the_matched_line() -> None:
    updated, matched = move_open_checkbox(SAMPLE_AGENT_QUEUE, "characterization")
    assert matched == "Add characterization tests #agent [repo::jmjava/dogfood-api]"
    assert "- [x] Add characterization tests #agent [repo::jmjava/dogfood-api]" in updated
    assert "- [x] Already done #agent" in updated
    assert "- [ ] Personal chore" in updated
    assert "- [ ] Write the Automations starter pack docs" in updated
    assert "- not a checkbox" in updated
    assert "## Inbox" in updated
    assert "## Later" in updated
    assert parse_open_checkboxes(updated) == [
        "Personal chore",
        "Write the Automations starter pack docs",
    ]


def test_move_open_checkbox_preserves_bullet_marker() -> None:
    text = "* [ ] Starred chore\n- [ ] Dash chore\n"
    updated, matched = move_open_checkbox(text, "Starred")
    assert matched == "Starred chore"
    assert updated == "* [x] Starred chore\n- [ ] Dash chore\n"


def test_move_open_checkbox_redacts_secrets_on_rewritten_line() -> None:
    text = "- [ ] Rotate password=hunter2 #agent\n- [ ] Keep this\n"
    updated, matched = move_open_checkbox(text, "Rotate")
    assert SECRET_PLACEHOLDER in matched
    assert "hunter2" not in matched
    assert "hunter2" not in updated
    assert f"- [x] Rotate {SECRET_PLACEHOLDER} #agent" in updated
    assert "- [ ] Keep this" in updated


def test_move_open_checkbox_missing_and_ambiguous() -> None:
    with pytest.raises(TaskMatchError, match="No matching"):
        move_open_checkbox(SAMPLE_AGENT_QUEUE, "missing")
    with pytest.raises(TaskMatchError, match="Ambiguous"):
        move_open_checkbox("- [ ] Add tests\n- [ ] Add tests later\n", "Add")
    with pytest.raises(TaskMatchError, match="No matching"):
        move_open_checkbox("# Agent Queue\n\n- [x] Already done\n", "Already")


def test_heading_time_uses_timezone_name() -> None:
    stamp = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))
    assert format_heading_time(stamp) == "11:42 EDT"
