from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from obsidian_dev_memory.markdown import (
    SECRET_PLACEHOLDER,
    append_under_heading,
    bullet_list,
    format_frontmatter,
    format_heading_time,
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


def test_heading_time_uses_timezone_name() -> None:
    stamp = datetime(2026, 8, 22, 11, 42, tzinfo=ZoneInfo("America/New_York"))
    assert format_heading_time(stamp) == "11:42 EDT"
