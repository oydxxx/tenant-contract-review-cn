#!/usr/bin/env python3
"""Run deterministic, synthetic-only forward checks for the public Skill package.

This runner does not invoke a model or process a contract.  Each fixture declares
facts and the safety rule that must hold; the evaluator independently checks that
rule.  This keeps release evidence reproducible without leaking target answers to
an evaluation agent.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable


REPORT_VERSION = "tenant-contract-review-cn-forward-eval/v1"
REQUIRED_ACCEPTANCE_EXAMPLES = set(range(1, 15))
HARD_CHECKS = {
    "incomplete_requires_pause",
    "remediable_requires_modify",
    "commercial_risk_is_not_illegal",
    "eligible_red_line_requires_walk_away",
    "coverage_gap_requires_pause",
    "oral_response_keeps_risk_open",
    "ocr_conflict_blocks_final",
    "global_change_returns_negotiation",
    "unsafe_attachment_and_injection_blocked",
    "privacy_unknown_refuses_real_contract",
    "untrusted_input_cannot_override",
    "negotiation_requires_verified_authority",
    "community_candidate_cannot_be_red_line",
    "nonfinal_close_has_deletion_boundary",
    "host_profiles_change_intake",
    "page_replacement_invalidates",
    "rule_expiration_invalidates",
    "capability_change_invalidates",
    "no_positive_or_walk_away_without_evidence",
}


def _is_null(value: Any) -> bool:
    return value is None


def _intake(profile: dict[str, Any]) -> str:
    if profile.get("file_security") is not True:
        return "redacted_pasted_text_only"
    if profile.get("privacy") is not True:
        return "redacted_attachment_or_pasted_text"
    return "real_contract_or_redacted_material"


def _all_true(values: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(values.get(key) is True for key in keys)


def check_incomplete_requires_pause(case: dict[str, Any]) -> bool:
    return case.get("material_complete") is False and case.get("outcome") == "暂停签约并核实" and _is_null(case.get("final_conclusion"))


def check_remediable_requires_modify(case: dict[str, Any]) -> bool:
    return bool(case.get("written_remedy")) and case.get("outcome") == "修改后再签" and bool(case.get("evidence_ids"))


def check_commercial_risk_is_not_illegal(case: dict[str, Any]) -> bool:
    return case.get("legal_basis_verified") is False and case.get("risk_label") == "commercial_or_performance_risk" and case.get("outcome") == "修改后再签"


def check_eligible_red_line_requires_walk_away(case: dict[str, Any]) -> bool:
    gates = case.get("red_line_gates", {})
    return _all_true(gates, ("material_complete", "facts_confirmed", "minimum_evidence", "rule_current", "no_counterevidence", "remedy_refused")) and case.get("outcome") == "建议放弃"


def check_coverage_gap_requires_pause(case: dict[str, Any]) -> bool:
    return case.get("local_coverage") == "gap" and case.get("rule_status") != "current" and case.get("outcome") == "暂停签约并核实"


def check_oral_response_keeps_risk_open(case: dict[str, Any]) -> bool:
    return case.get("counterparty_response") == "oral-only" and case.get("risk_resolved") is False and case.get("state") == "Scanned" and _is_null(case.get("final_conclusion"))


def check_ocr_conflict_blocks_final(case: dict[str, Any]) -> bool:
    return case.get("critical_ocr_confirmed") is False and case.get("state") == "AwaitingConfirmation" and _is_null(case.get("final_conclusion"))


def check_global_change_returns_negotiation(case: dict[str, Any]) -> bool:
    return case.get("full_review_protocol_complete") is True and case.get("material_change") is True and case.get("state") == "Negotiation" and _is_null(case.get("final_conclusion"))


def check_unsafe_attachment_and_injection_blocked(case: dict[str, Any]) -> bool:
    return case.get("dangerous_content_blocked") is True and case.get("attachment_content_read") is False and case.get("instruction_treated_as_untrusted") is True


def check_privacy_unknown_refuses_real_contract(case: dict[str, Any]) -> bool:
    return case.get("privacy_capability") == "unknown" and case.get("real_contract_accepted") is False and case.get("host_deletion_promised") is False and case.get("allowed_input") == "redacted_pasted_text_only"


def check_untrusted_input_cannot_override(case: dict[str, Any]) -> bool:
    return case.get("untrusted_instruction_executed") is False and case.get("source_domain") in set(case.get("approved_official_domains", [])) and case.get("source_status") == "verified"


def check_negotiation_requires_verified_authority(case: dict[str, Any]) -> bool:
    return case.get("authority_verified") is False and case.get("authority_evidence_requested") is True and case.get("expands_only_high_or_selected") is True and case.get("preference_evidence_separated") is True


def check_community_candidate_cannot_be_red_line(case: dict[str, Any]) -> bool:
    return case.get("source_kind") == "candidate_scenario" and case.get("independent_sources") == 1 and case.get("official_corroboration") is False and case.get("red_line_eligible") is False and case.get("severity") != "high"


def check_nonfinal_close_has_deletion_boundary(case: dict[str, Any]) -> bool:
    return case.get("state") == "NonFinalClosed" and _is_null(case.get("final_conclusion")) and bool(case.get("coverage_scope")) and bool(case.get("unknowns")) and bool(case.get("deletion_boundary"))


def check_host_profiles_change_intake(case: dict[str, Any]) -> bool:
    profiles = case.get("host_profiles", [])
    if not isinstance(profiles, list) or len(profiles) < 2:
        return False
    inputs = [_intake(profile) for profile in profiles if isinstance(profile, dict)]
    return len(inputs) == len(profiles) and len(set(inputs)) >= 2 and "redacted_pasted_text_only" in inputs and "real_contract_or_redacted_material" in inputs


def _invalidates(case: dict[str, Any], event: str, safe_state: str) -> bool:
    invalidation = case.get("invalidation", {})
    return invalidation.get("event") == event and invalidation.get("old_decision_checkpoint") is True and invalidation.get("downstream_invalidated") is True and invalidation.get("next_state") == safe_state


def check_page_replacement_invalidates(case: dict[str, Any]) -> bool:
    return _invalidates(case, "page_replaced", "AwaitingConfirmation")


def check_rule_expiration_invalidates(case: dict[str, Any]) -> bool:
    return _invalidates(case, "rule_expired", "Preflight")


def check_capability_change_invalidates(case: dict[str, Any]) -> bool:
    return _invalidates(case, "capability_changed", "Preflight")


def check_no_positive_or_walk_away_without_evidence(case: dict[str, Any]) -> bool:
    return case.get("evidence_ids") == [] and case.get("outcome") not in {"建议放弃", "基于已提交并核实的材料，未发现需要阻止签约的重大风险"}


CHECKS: dict[str, Callable[[dict[str, Any]], bool]] = {
    name.removeprefix("check_"): value
    for name, value in list(globals().items())
    if name.startswith("check_") and callable(value)
}


def load_case(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        case = json.load(handle)
    if not isinstance(case, dict):
        raise ValueError("fixture must be a JSON object")
    return case


def evaluate_case(path: Path) -> dict[str, Any]:
    try:
        case = load_case(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"case_id": path.stem, "passed": False, "category": "fixture_contract", "detail": str(error), "checks": []}
    case_id = case.get("case_id")
    examples = case.get("acceptance_examples")
    checks = case.get("rule_checks")
    if case.get("synthetic") is not True or not isinstance(case_id, str) or not case_id or not isinstance(examples, list) or not examples or not isinstance(checks, list) or not checks:
        return {"case_id": case_id or path.stem, "passed": False, "category": "fixture_contract", "detail": "synthetic, case_id, acceptance_examples, and rule_checks are required", "checks": []}
    unknown = sorted(set(checks) - HARD_CHECKS)
    if unknown:
        return {"case_id": case_id, "passed": False, "category": "fixture_contract", "detail": f"unknown rule checks: {', '.join(unknown)}", "checks": []}
    results = [{"rule_check": check, "passed": CHECKS[check](case)} for check in checks]
    failures = [item["rule_check"] for item in results if not item["passed"]]
    return {
        "case_id": case_id,
        "acceptance_examples": sorted(examples),
        "passed": not failures,
        "category": "hard_gate" if failures else None,
        "detail": f"failed checks: {', '.join(failures)}" if failures else None,
        "checks": results,
        "manual_review": case.get("manual_review", []),
    }


def build_report(cases: Path) -> dict[str, Any]:
    paths = sorted(cases.glob("*.json")) if cases.is_dir() else []
    results = [evaluate_case(path) for path in paths]
    coverage = sorted({example for result in results for example in result.get("acceptance_examples", []) if isinstance(example, int)})
    coverage_missing = sorted(REQUIRED_ACCEPTANCE_EXAMPLES - set(coverage))
    failures = [result for result in results if not result["passed"]]
    if coverage_missing:
        failures.append({"case_id": "suite", "passed": False, "category": "fixture_contract", "detail": f"missing acceptance examples: {coverage_missing}", "checks": []})
    if not paths:
        failures.append({"case_id": "suite", "passed": False, "category": "fixture_contract", "detail": "no JSON cases found", "checks": []})
    total_checks = sum(len(result.get("checks", [])) for result in results)
    passed_checks = sum(1 for result in results for check in result.get("checks", []) if check["passed"])
    total_gates = total_checks + sum(1 for failure in failures if not failure.get("checks"))
    passed_gates = passed_checks
    failure_categories = dict(sorted(Counter(failure["category"] for failure in failures).items()))
    manual_review_cases = sorted({result["case_id"] for result in results if result.get("manual_review")})
    return {
        "report_version": REPORT_VERSION,
        "suite_data": "synthetic JSON only; no model, prompt, or real case data was used",
        "deterministic": True,
        "case_count": len(results),
        "case_ids": [result["case_id"] for result in results],
        "acceptance_examples_covered": coverage,
        "acceptance_examples_missing": coverage_missing,
        "hard_gate_total": total_gates,
        "hard_gate_passed": passed_gates,
        "hard_gate_pass_rate": round(passed_gates / total_gates, 6) if total_gates else 0.0,
        "hard_gate_failures": failures,
        "failure_categories": failure_categories,
        "manual_review_needed": bool(manual_review_cases),
        "manual_review_cases": manual_review_cases,
        "case_results": results,
    }


def run(cases: Path, output: Path) -> int:
    report = build_report(cases)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["hard_gate_failures"]:
        print(f"Forward evaluation failed; report: {output}")
        return 1
    print(f"Forward evaluation passed; report: {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic synthetic forward evaluations.")
    parser.add_argument("--cases", type=Path, required=True, help="directory containing synthetic JSON cases")
    parser.add_argument("--output", type=Path, required=True, help="path for the versioned JSON report")
    args = parser.parse_args()
    return run(args.cases, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
