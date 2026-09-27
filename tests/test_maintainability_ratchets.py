"""Decision checks for the maintainability gates."""

from __future__ import annotations

import json
from pathlib import Path

from hotspot import hotspot_failures
from mutation_gate import mutation_regression
from ratchet_complexity import classify_functions
from ruff_baseline_gate import findings_beyond_baseline

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_complexity_is_visible_and_not_a_failure() -> None:
    failures, legacy = classify_functions({"old": 26}, {"old": 26}, max_ccn=10)
    assert failures == []
    assert legacy == ["legacy old ccn=26"]


def test_new_function_over_threshold_fails() -> None:
    failures, legacy = classify_functions({}, {"fresh": 11}, max_ccn=10)
    assert failures == ["new fresh ccn=11"]
    assert legacy == []


def test_worsened_function_fails() -> None:
    failures, _legacy = classify_functions({"old": 3}, {"old": 4}, max_ccn=10)
    assert failures == ["worsened old 3->4"]


def test_hotspot_fails_only_for_complex_frequent_changed_files() -> None:
    counts = {"hot.py": 20, "quiet.py": 1}
    frequent, _hot = hotspot_failures(["hot.py"], counts, {"hot.py": 12}, top_n=1, max_ccn=10)
    quiet, _ignored = hotspot_failures(["quiet.py"], counts, {"quiet.py": 12}, top_n=1, max_ccn=10)
    simple, _also = hotspot_failures(["hot.py"], counts, {"hot.py": 4}, top_n=1, max_ccn=10)
    assert frequent == ["hot.py"]
    assert quiet == []
    assert simple == []


def test_ruff_baseline_flags_only_new_findings(tmp_path: Path) -> None:
    baseline = [{"filename": "a.py", "code": "E501", "message": "long"}]
    current = baseline + [{"filename": "b.py", "code": "F401", "message": "unused"}]
    extra = findings_beyond_baseline(baseline, current, tmp_path)
    assert extra == [(("b.py", "F401", "unused"), 1)]


def test_ruff_and_mutation_gates_do_not_rewrite_baselines() -> None:
    ruff_gate = (REPO_ROOT / "scripts" / "ruff_baseline_gate.py").read_text(encoding="utf-8")
    mutation_gate = (REPO_ROOT / "scripts" / "mutation_gate.py").read_text(encoding="utf-8")
    for source in (ruff_gate, mutation_gate):
        assert "write_text" not in source
        assert "write_bytes" not in source
        assert 'mode="w"' not in source
        assert "mode='w'" not in source
    workflow = (REPO_ROOT / ".github" / "workflows" / "pytest.yml").read_text(encoding="utf-8")
    assert "write-baseline" not in workflow
    assert "ruff check --fix" not in workflow


def test_mutation_regression_uses_real_counts() -> None:
    baseline = {"survived": 2, "total": 10, "killed": 8}
    assert mutation_regression(baseline, {"survived": 2, "total": 10, "killed": 8}) == []
    increased = mutation_regression(baseline, {"survived": 3, "total": 10, "killed": 7})
    assert increased
    empty = mutation_regression(baseline, {"survived": 0, "total": 0, "killed": 0})
    assert empty
    encoded = json.dumps(baseline)
    assert "survived" in encoded
