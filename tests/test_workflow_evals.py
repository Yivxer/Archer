from __future__ import annotations

import json

from evals.run_workflow_evals import BASELINE_PATH, CASES_PATH, evaluate_cases


def _actual() -> dict:
    return evaluate_cases(json.loads(CASES_PATH.read_text(encoding="utf-8")))


def test_workflow_eval_baseline_matches_production_routes():
    expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert _actual() == expected


def test_hugo_eval_contract_keeps_readonly_turns_side_effect_free():
    actual = _actual()
    for case_id in ("hugo.capability", "hugo.review", "hugo.negated"):
        assert actual[case_id]["side_effect_level"] == "none"
        assert actual[case_id]["wants_publish_workflow"] is False


def test_hugo_eval_contract_requires_approval_for_publish_and_delete():
    actual = _actual()
    for case_id in ("hugo.publish", "hugo.delete"):
        assert actual[case_id]["side_effect_level"] == "approval_required"
        assert actual[case_id]["wants_publish_workflow"] is True
        assert actual[case_id]["needs_tools"] is True
