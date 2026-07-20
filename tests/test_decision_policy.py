import copy
import importlib.util
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPOSITORY_ROOT / "tests/fixtures/synthetic"
REFERENCE_DIRECTORY = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references"
SCRIPT_PATH = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/scripts/validate_decisions.py"
SPEC = importlib.util.spec_from_file_location("validate_decisions", SCRIPT_PATH)
assert SPEC and SPEC.loader
validate_decisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_decisions)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class DecisionPolicyTests(unittest.TestCase):
    def test_verified_red_line_refusal_is_walk_away_only_when_all_gates_pass(self) -> None:
        case = fixture("decision-walk-away.json")
        self.assertEqual(validate_decisions.OUTCOME_WALK_AWAY, validate_decisions.compute_outcome(case))
        incomplete = copy.deepcopy(case)
        incomplete["state_guard"]["material_complete"] = False
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(incomplete))
        with_counterevidence = copy.deepcopy(case)
        with_counterevidence["findings"][0]["counterevidence_present"] = True
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(with_counterevidence))

    def test_authority_fees_or_local_rule_unknowns_pause(self) -> None:
        case = fixture("decision-pause-authority.json")
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(case))
        for unknown in ("rental-authority", "fee-basis", "local-rule-applicability"):
            probe = copy.deepcopy(case)
            probe["unknowns"] = [unknown]
            self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(probe))
        expired = copy.deepcopy(case)
        expired["unknowns"] = []
        expired["findings"] = []
        expired["rules"][0]["status"] = "expired"
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(expired))

    def test_written_remedy_for_unfavorable_clause_is_modify_before_sign(self) -> None:
        case = fixture("decision-modify.json")
        self.assertEqual(validate_decisions.OUTCOME_MODIFY, validate_decisions.compute_outcome(case))
        self.assertTrue(case["findings"][0]["written_remedy_available"])

    def test_missing_deposit_return_deduction_and_repair_terms_are_findings(self) -> None:
        case = fixture("decision-missing-terms.json")
        self.assertEqual(validate_decisions.OUTCOME_MODIFY, validate_decisions.compute_outcome(case))
        missing_terms = {finding["missing_term"] for finding in case["findings"]}
        self.assertTrue(validate_decisions.MANDATORY_MISSING_TERMS <= missing_terms)
        self.assertEqual([], validate_decisions.validate_case(case))

    def test_priority_keeps_major_unknown_above_remedy_and_unverified_red_line(self) -> None:
        case = fixture("decision-priority.json")
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(case))
        self.assertTrue(any(finding["written_remedy_available"] for finding in case["findings"]))

    def test_ocr_incomplete_material_and_expired_rules_block_positive_and_walk_away(self) -> None:
        case = fixture("decision-guard-blockers.json")
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(case))
        for guard_name in ("material_complete", "critical_ocr_confirmed", "key_fields_confirmed"):
            probe = fixture("decision-walk-away.json")
            probe["state_guard"][guard_name] = False
            self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(probe))
        positive = fixture("decision-positive-trace.json")
        positive["rules"][0]["status"] = "expired"
        self.assertEqual(validate_decisions.OUTCOME_PAUSE, validate_decisions.compute_outcome(positive))

    def test_each_outcome_has_version_evidence_rule_and_state_trace(self) -> None:
        outcomes = set()
        for path in sorted(FIXTURES.glob("decision-*.json")):
            case = fixture(path.name)
            decision = validate_decisions.build_decision(case)
            outcomes.add(decision["outcome"])
            self.assertEqual(case["material_inventory_version"], decision["material_inventory_version"])
            self.assertTrue(decision["evidence_ids"])
            self.assertTrue(decision["rule_references"])
            self.assertEqual(case["state_guard"]["case_state"], decision["decision_state_guard"]["case_state"])
            self.assertEqual([], validate_decisions.validate_case(case))
        self.assertEqual(set(validate_decisions.OUTCOMES), outcomes)

    def test_references_fix_five_categories_priority_red_line_and_output_order(self) -> None:
        taxonomy = (REFERENCE_DIRECTORY / "risk-taxonomy.md").read_text(encoding="utf-8")
        policy = (REFERENCE_DIRECTORY / "decision-policy.md").read_text(encoding="utf-8")
        output = (REFERENCE_DIRECTORY / "output-contract.md").read_text(encoding="utf-8")
        for category in validate_decisions.FINDING_CATEGORIES:
            self.assertIn(category, taxonomy)
        for required in (
            "材料完整", "关键 OCR", "规则过期", "pause_and_verify",
            "recommend_walk_away_if_decision_gates_pass", "不替代律师",
        ):
            self.assertIn(required, policy + output)
        self.assertLess(output.index("总体结论及证据边界"), output.index("红线或重大未知项"))
        self.assertLess(output.index("红线或重大未知项"), output.index("主要风险"))


if __name__ == "__main__":
    unittest.main()
