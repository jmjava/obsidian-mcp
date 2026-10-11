"""Stable quality-pool contract returned by the MCP tool.

Today's held pull requests stay in the vault pool note. This module is the
process: how a seat is chosen, and when a commit counts as done.
"""

from __future__ import annotations

from typing import Any

QUALITY_POOL_CAP = 7

MAINTAINABILITY_TECHNIQUES = (
    "clean_as_you_code",
    "hotspot",
    "fitness",
    "static_baseline",
    "mutation",
)

SELECTION = (
    (
        "A green open pull request on a repo with no live seat. "
        "Skip items the current pool note holds."
    ),
    (
        "The first maintainability technique that is not already on origin/main, "
        "on the busiest remaining repo. One pull request, then stop."
    ),
    (
        "If all five techniques are already on origin/main, "
        "the seat exits and the pool refills."
    ),
)

WORKFLOW = (
    (
        "Read .github/workflows and run those test and lint commands locally. "
        "Commit and push only after that local run exits 0."
    ),
    "After push, read gh pr checks until that run finishes. Pending is not a pass.",
    (
        "If any check in that run fails, fix the code and start again. "
        "A failing check is still a failure when branch protection does not require it."
    ),
    "Squash-merge only when every check in that run is success.",
    (
        "The only open outcome is a green pull request that GitHub rejects "
        "because the token cannot edit .github/workflows. "
        "Do not open a second pull request for the same change."
    ),
)

STOP = (
    "Never open a pull request against embabel/guide.",
    "Do not run mutmut or PIT locally.",
    "Do not raise a frozen mutation ceiling.",
    "Do not refresh a baseline to hide findings.",
    "Do not split a function only to satisfy a complexity number.",
    "OpenGolf and course-builder stay off the list.",
)


def quality_pool_flow() -> dict[str, Any]:
    """Return the quality-pool contract. Does not read or write the vault."""
    return {
        "cap": QUALITY_POOL_CAP,
        "refill_when_seat_exits": True,
        "techniques": list(MAINTAINABILITY_TECHNIQUES),
        "selection": list(SELECTION),
        "workflow": list(WORKFLOW),
        "stop": list(STOP),
    }
