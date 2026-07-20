#!/usr/bin/env python3
"""Validate U5 decision invariants against synthetic, versioned cases.

This checks the encoded safety thresholds.  It does not decide any real tenancy
dispute or prove that a legal source is current for an individual case.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "synthetic"
RED_LINES_PATH = SKILL_ROOT / "references" / "red-lines.yaml"

OUTCOME_WALK_AWAY = "建议放弃"
OUTCOME_PAUSE = "暂停签约并核实"
OUTCOME_MODIFY = "修改后再签"
OUTCOME_POSITIVE = "基于已提交并核实的材料，未发现需要阻止签约的重大风险"
OUTCOMES = (OUTCOME_WALK_AWAY, OUTCOME_PAUSE, OUTCOME_MODIFY, OUTCOME_POSITIVE)

FINDING_CATEGORIES = {
    "possibly_unlawful_or_invalid",
    "tenant_unfavorable_but_not_necessarily_unlawful",
    "material_term_missing",
    "external_verification_required",
    "currently_indeterminate",
}
FINDING_FIELDS = {
    "finding_id", "category", "title", "material_inventory_version", "evidence_ids",
    "rule_id", "rule_version", "applicability", "confidence", "consequence", "severity",
    "recommended_action", "state_guard", "legal_fact", "product_risk_judgment", "negotiation_advice",
}
REQUIRED_GUARDS = {
    "case_state", "material_complete", "critical_ocr_confirmed", "key_fields_confirmed",
    "source_reliable", "no_evidence_conflict", "rule_pack_version", "local_rule_coverage_verified",
}
MANDATORY_MISSING_TERMS = {
    "deposit_return_deadline", "deposit_deduction_standard", "repair_time_limit",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path.name}: fixture must be an object")
    return document


def red_line_index(path: Path = RED_LINES_PATH) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    records = document.get("records", []) if isinstance(document, dict) else []
    return {
        record["id"]: record for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def unknown_reasons(case: dict[str, Any]) -> list[str]:
    guard = case.get("state_guard", {})
    if not isinstance(guard, dict):
        return ["invalid-state-guard"]
    reasons: list[str] = []
    if guard.get("case_state") not in {"Scanned", "GlobalFinalReview"}:
        reasons.append("stage-not-reviewable")
    for field, reason in (
        ("material_complete", "material-incomplete"),
        ("critical_ocr_confirmed", "critical-ocr-unconfirmed"),
        ("key_fields_confirmed", "key-fields-unconfirmed"),
        ("source_reliable", "source-unreliable"),
        ("no_evidence_conflict", "evidence-conflict"),
        ("local_rule_coverage_verified", "local-rule-coverage-gap"),
    ):
        if guard.get(field) is not True:
            reasons.append(reason)
    for rule in case.get("rules", []):
        if not isinstance(rule, dict):
            reasons.append("invalid-rule-record")
            continue
        if rule.get("status") != "current":
            reasons.append("rule-not-current")
        if rule.get("applicability") != "verified":
            reasons.append("rule-applicability-unverified")
    for label in case.get("unknowns", []):
        reasons.append(f"material-unknown:{label}")
    for finding in case.get("findings", []):
        if not isinstance(finding, dict):
            reasons.append("invalid-finding")
        elif finding.get("category") in {"external_verification_required", "currently_indeterminate"}:
            reasons.append(f"unresolved:{finding.get('finding_id', 'unknown')}")
        elif finding.get("red_line_id") and finding.get("counterevidence_present") is True:
            reasons.append(f"red-line-counterevidence:{finding.get('finding_id', 'unknown')}")
    return sorted(set(reasons))


def red_line_is_walk_away_eligible(
    finding: dict[str, Any], red_lines: dict[str, dict[str, Any]], unknowns: list[str]
) -> bool:
    red_line = red_lines.get(finding.get("red_line_id"))
    if not red_line or unknowns:
        return False
    return (
        finding.get("severity") == "high"
        and finding.get("confidence") == "high"
        and finding.get("red_line_established") is True
        and finding.get("minimum_evidence_satisfied") is True
        and finding.get("counterevidence_present") is False
        and finding.get("refusal_or_no_acceptable_remedy") is True
        and red_line.get("on_refusal_result") == "recommend_walk_away_if_decision_gates_pass"
        and red_line.get("uncertainty_result") == "pause_and_verify"
    )


def compute_outcome(case: dict[str, Any], red_lines: dict[str, dict[str, Any]] | None = None) -> str:
    """Apply KTD11 in order; this returns one of the four allowed outcomes."""
    red_lines = red_lines or red_line_index()
    unknowns = unknown_reasons(case)
    findings = [item for item in case.get("findings", []) if isinstance(item, dict)]
    if any(red_line_is_walk_away_eligible(finding, red_lines, unknowns) for finding in findings):
        return OUTCOME_WALK_AWAY
    if unknowns:
        return OUTCOME_PAUSE
    if any(finding.get("written_remedy_available") is True for finding in findings):
        return OUTCOME_MODIFY
    return OUTCOME_POSITIVE


def build_decision(case: dict[str, Any], red_lines: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    reasons = unknown_reasons(case)
    outcome = compute_outcome(case, red_lines)
    findings = [item for item in case.get("findings", []) if isinstance(item, dict)]
    evidence_ids = sorted({
        *case.get("decision_evidence_ids", []),
        *(evidence_id for finding in findings for evidence_id in finding.get("evidence_ids", [])),
    })
    rule_references = sorted({
        *(tuple(reference) for reference in case.get("decision_rule_references", [])),
        *((finding.get("rule_id"), finding.get("rule_version"))
          for finding in findings if finding.get("rule_id") and finding.get("rule_version")),
    })
    if outcome == OUTCOME_WALK_AWAY:
        primary_reasons = ["verified-high-confidence-red-line-refusal-or-no-remedy"]
    elif outcome == OUTCOME_PAUSE:
        primary_reasons = reasons
    elif outcome == OUTCOME_MODIFY:
        primary_reasons = ["written-remedy-available"]
    else:
        primary_reasons = ["no-higher-priority-decision-trigger"]
    return {
        "case_id": case.get("case_id"),
        "outcome": outcome,
        "material_inventory_version": case.get("material_inventory_version"),
        "evidence_ids": evidence_ids,
        "rule_references": [
            {"rule_id": rule_id, "rule_version": rule_version}
            for rule_id, rule_version in rule_references
        ],
        "findings_checkpoint": case.get("findings_checkpoint"),
        "decision_state_guard": {
            "case_state": case.get("state_guard", {}).get("case_state"),
            "passed": not reasons,
            "failed_reasons": reasons,
            "rule_pack_version": case.get("state_guard", {}).get("rule_pack_version"),
        },
        "primary_reasons": primary_reasons,
        "verified_scope": case.get("verified_scope", []),
        "remaining_unknowns": case.get("unknowns", []),
        "local_rule_boundary": case.get("local_rule_boundary"),
        "pre_signing_checklist": case.get("pre_signing_checklist", []),
    }


def validate_finding(finding: Any, case: dict[str, Any], index: int) -> list[str]:
    label = f"{case.get('case_id', 'unknown')} findings[{index}]"
    if not isinstance(finding, dict):
        return [f"{label}: must be an object"]
    errors: list[str] = []
    missing = FINDING_FIELDS - set(finding)
    if missing:
        errors.append(f"{label}: missing fields: {', '.join(sorted(missing))}")
    if finding.get("category") not in FINDING_CATEGORIES:
        errors.append(f"{label}: category must be one of the fixed five")
    if finding.get("material_inventory_version") != case.get("material_inventory_version"):
        errors.append(f"{label}: material version must match the decision input")
    if not isinstance(finding.get("evidence_ids"), list) or not finding.get("evidence_ids"):
        errors.append(f"{label}: evidence_ids must be non-empty")
    if not isinstance(finding.get("applicability"), dict):
        errors.append(f"{label}: applicability must be structured")
    if not isinstance(finding.get("state_guard"), dict):
        errors.append(f"{label}: state_guard must be structured")
    return errors


def validate_case(case: dict[str, Any], red_lines: dict[str, dict[str, Any]] | None = None) -> list[str]:
    label = str(case.get("case_id", "unknown-case"))
    errors: list[str] = []
    for key in (
        "synthetic", "case_id", "material_inventory_version", "state_guard", "rules", "findings",
        "findings_checkpoint", "expected_outcome", "verified_scope", "local_rule_boundary", "pre_signing_checklist",
        "decision_evidence_ids", "decision_rule_references",
    ):
        if key not in case:
            errors.append(f"{label}: missing {key}")
    if case.get("synthetic") is not True:
        errors.append(f"{label}: fixture must be explicitly synthetic")
    guard = case.get("state_guard")
    if not isinstance(guard, dict):
        errors.append(f"{label}: state_guard must be an object")
    else:
        missing_guards = REQUIRED_GUARDS - set(guard)
        if missing_guards:
            errors.append(f"{label}: missing state guards: {', '.join(sorted(missing_guards))}")
    if not isinstance(case.get("rules"), list):
        errors.append(f"{label}: rules must be a list")
    if not isinstance(case.get("findings"), list):
        errors.append(f"{label}: findings must be a list")
    else:
        for index, finding in enumerate(case["findings"]):
            errors.extend(validate_finding(finding, case, index))
            if isinstance(finding, dict) and finding.get("red_line_id"):
                red_line = (red_lines or red_line_index()).get(finding["red_line_id"])
                if not red_line:
                    errors.append(f"{label}: unknown red line {finding['red_line_id']}")
                elif (
                    red_line.get("on_refusal_result") != "recommend_walk_away_if_decision_gates_pass"
                    or red_line.get("uncertainty_result") != "pause_and_verify"
                ):
                    errors.append(f"{label}: red-line semantics do not match U4")
    decision = build_decision(case, red_lines)
    if case.get("expected_outcome") not in OUTCOMES:
        errors.append(f"{label}: expected_outcome must be one of four outcomes")
    elif decision["outcome"] != case["expected_outcome"]:
        errors.append(f"{label}: expected {case['expected_outcome']}, got {decision['outcome']}")
    if not decision["material_inventory_version"] or not decision["evidence_ids"] or not decision["rule_references"]:
        errors.append(f"{label}: decision trace must include material version, evidence IDs, and rule versions")
    if not decision["decision_state_guard"]["case_state"]:
        errors.append(f"{label}: decision trace must include its stage guard")
    missing_terms = set(case.get("missing_terms_expected", []))
    if missing_terms:
        found_terms = {
            finding.get("missing_term") for finding in case.get("findings", [])
            if isinstance(finding, dict) and finding.get("category") == "material_term_missing"
        }
        absent = missing_terms - found_terms
        if absent:
            errors.append(f"{label}: missing required missing-term findings: {', '.join(sorted(absent))}")
    return errors


def validate_fixtures(fixtures: Path = FIXTURES) -> list[str]:
    errors: list[str] = []
    try:
        red_lines = red_line_index()
    except (OSError, yaml.YAMLError) as error:
        return [f"cannot load red lines: {error}"]
    for path in sorted(fixtures.glob("decision-*.json")):
        try:
            errors.extend(validate_case(load_json(path), red_lines))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}: {error}")
    if not list(fixtures.glob("decision-*.json")):
        errors.append("no decision fixtures found")
    return errors


def main() -> int:
    errors = validate_fixtures()
    if errors:
        print("Decision validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Decision validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
