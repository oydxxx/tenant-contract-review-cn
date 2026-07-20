#!/usr/bin/env python3
"""Validate the U4 source-governance package without trusting its contents."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = SKILL_ROOT / "references"
CITY_FILES = ("city-beijing.yaml", "city-shanghai.yaml", "city-guangzhou.yaml", "city-shenzhen.yaml")
REQUIRED_RECORD_FIELDS = {
    "id", "source_kind", "authority_category", "publisher", "final_domain", "source_url",
    "final_url_verified", "redirect_chain", "scope", "reviewed_on", "review_due_on", "status", "risk_propositions",
}
REQUIRED_SCOPE_FIELDS = {"geography", "effective_from", "effective_to", "subjects", "topics"}
OFFICIAL_DOMAIN_SUFFIXES = (".gov.cn", ".samr.gov.cn")
LEGAL_AUTHORITY_CATEGORIES = {"administrative_regulation", "local_regulation", "law"}
SENSITIVE_QUERY_PATTERNS = (
    r"身份证", r"银行卡", r"账号", r"合同原文", r"合同第\s*\d+\s*条", r"住址", r"详细地址",
    r"张三|李四|王五|某小区", r"(?:省|市|区|县).{0,12}(?:路|街|号|小区|室)",
    r"\b1[3-9]\d{9}\b", r"\b\d{15,18}[0-9Xx]\b", r"\b\d{16,19}\b",
)


def load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def is_official_final_url(record: dict[str, object]) -> bool:
    url = record.get("source_url")
    domain = record.get("final_domain")
    if not isinstance(url, str) or not isinstance(domain, str):
        return False
    parsed = urlparse(url)
    redirect_chain = record.get("redirect_chain")
    if not isinstance(redirect_chain, list) or not all(isinstance(item, str) for item in redirect_chain):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == domain
        and record.get("final_url_verified") is True
        and domain.endswith(OFFICIAL_DOMAIN_SUFFIXES)
        and (not redirect_chain or redirect_chain[-1] == url)
    )


def has_complete_scope(record: dict[str, object]) -> bool:
    scope = record.get("scope")
    return isinstance(scope, dict) and REQUIRED_SCOPE_FIELDS <= set(scope) and all(
        scope.get(field) not in (None, "", []) for field in ("geography", "subjects", "topics")
    )


def is_effective_on(record: dict[str, object], today: date) -> bool:
    scope = record.get("scope")
    if not isinstance(scope, dict):
        return False
    try:
        effective_from = date.fromisoformat(str(scope.get("effective_from")))
        effective_to_value = scope.get("effective_to")
        effective_to = date.fromisoformat(str(effective_to_value)) if effective_to_value else None
    except ValueError:
        return False
    return effective_from <= today and (effective_to is None or today <= effective_to)


def legal_conclusion_status(record: dict[str, object], today: date | None = None) -> str:
    """Return `legal_basis` only for a complete, current official record."""
    today = today or date.today()
    if record.get("source_kind") != "legal_basis":
        return "not_legal_basis"
    if record.get("authority_category") not in LEGAL_AUTHORITY_CATEGORIES:
        return "requires_fresh_review"
    if not is_official_final_url(record) or not has_complete_scope(record):
        return "requires_fresh_review"
    if record.get("status") != "current" or not is_effective_on(record, today):
        return "requires_fresh_review"
    due = record.get("review_due_on")
    try:
        due_date = date.fromisoformat(str(due))
    except ValueError:
        return "requires_fresh_review"
    return "legal_basis" if due_date >= today else "requires_fresh_review"


def is_safe_realtime_query(query: str) -> bool:
    return isinstance(query, str) and bool(query.strip()) and not any(
        re.search(pattern, query, flags=re.IGNORECASE) for pattern in SENSITIVE_QUERY_PATTERNS
    )


def city_coverage(city_document: dict[str, object], city: str) -> str:
    if city in {"Beijing", "Shanghai", "Guangzhou", "Shenzhen"}:
        return str(city_document.get("coverage_status", "coverage_gap"))
    return "coverage_gap"


def validate_legal_record(record: object, source_name: str) -> list[str]:
    if not isinstance(record, dict):
        return [f"{source_name}: record must be a mapping"]
    errors: list[str] = []
    missing = REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        errors.append(f"{source_name}: missing fields: {', '.join(sorted(missing))}")
    if record.get("source_kind") == "legal_basis" and not is_official_final_url(record):
        errors.append(f"{source_name}: legal basis must use a verified final official HTTPS domain")
    if record.get("source_kind") == "legal_basis" and not has_complete_scope(record):
        errors.append(f"{source_name}: legal basis scope is incomplete")
    if not isinstance(record.get("risk_propositions"), list) or not record.get("risk_propositions"):
        errors.append(f"{source_name}: risk propositions must be a non-empty list")
    return errors


def validate_package(references: Path = REFERENCES, as_of: date | None = None) -> list[str]:
    errors: list[str] = []
    as_of = as_of or date.today()
    all_legal_ids: set[str] = set()
    documents: dict[str, dict[str, object]] = {}
    for filename in ("national-rules.yaml", *CITY_FILES):
        path = references / filename
        if not path.is_file():
            errors.append(f"missing source file: {filename}")
            continue
        document = load_yaml(path)
        if not isinstance(document, dict):
            errors.append(f"{filename}: document must be a mapping")
            continue
        documents[filename] = document
        records = document.get("records")
        if not isinstance(records, list):
            errors.append(f"{filename}: records must be a list")
            continue
        for index, record in enumerate(records):
            errors.extend(validate_legal_record(record, f"{filename}[{index}]"))
            if isinstance(record, dict) and record.get("source_kind") == "legal_basis":
                identifier = record.get("id")
                if not isinstance(identifier, str) or identifier in all_legal_ids:
                    errors.append(f"{filename}[{index}]: legal basis ID must be unique")
                elif legal_conclusion_status(record, as_of) != "legal_basis":
                    errors.append(f"{filename}[{index}]: legal basis is not usable without fresh review")
                else:
                    all_legal_ids.add(identifier)
    for filename, expected in zip(CITY_FILES, ("Beijing", "Shanghai", "Guangzhou", "Shenzhen")):
        document = documents.get(filename, {})
        status = city_coverage(document, expected)
        if expected == "Shenzhen":
            if status != "coverage_gap" or not document.get("coverage_gap"):
                errors.append("city-shenzhen.yaml: Shenzhen must disclose its current coverage gap")
        elif status != "covered":
            errors.append(f"{filename}: verified city overlay must be marked covered")
    red_lines = load_yaml(references / "red-lines.yaml")
    if not isinstance(red_lines, dict) or not isinstance(red_lines.get("records"), list):
        errors.append("red-lines.yaml: records must be a list")
    else:
        for index, record in enumerate(red_lines["records"]):
            if not isinstance(record, dict) or record.get("source_kind") != "red_line":
                errors.append(f"red-lines.yaml[{index}]: must be a red_line mapping")
                continue
            basis_ids = record.get("legal_basis_ids")
            if not isinstance(basis_ids, list) or not basis_ids or not set(basis_ids) <= all_legal_ids:
                errors.append(f"red-lines.yaml[{index}]: must cite valid legal_basis IDs only")
            if record.get("on_refusal_result") != "recommend_walk_away_if_decision_gates_pass":
                errors.append(f"red-lines.yaml[{index}]: refusal outcome must preserve the decision gates")
            if record.get("uncertainty_result") != "pause_and_verify":
                errors.append(f"red-lines.yaml[{index}]: uncertainty must downgrade to pause_and_verify")
    candidates = load_yaml(references / "community-scenarios.yaml")
    if not isinstance(candidates, dict) or not isinstance(candidates.get("records"), list):
        errors.append("community-scenarios.yaml: records must be a list")
    else:
        prohibited = re.compile(r"(知乎|tenant-point|黑名单|身份证|银行卡|@|http)", re.IGNORECASE)
        for index, record in enumerate(candidates["records"]):
            if not isinstance(record, dict) or record.get("source_kind") != "candidate_scenario":
                errors.append(f"community-scenarios.yaml[{index}]: must remain a candidate_scenario")
                continue
            if record.get("permitted_output") != "evidence request or negotiation question only":
                errors.append(f"community-scenarios.yaml[{index}]: candidate output is too broad")
            text = " ".join(str(value) for value in record.values())
            if prohibited.search(text):
                errors.append(f"community-scenarios.yaml[{index}]: contains prohibited personal, accusation, or copied-source content")
            if any(len(str(value)) > 500 for value in record.values()):
                errors.append(f"community-scenarios.yaml[{index}]: contains an overlong source excerpt")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the governed source package.")
    parser.add_argument("--as-of", type=date.fromisoformat, help="ISO date for a reproducible historical validation")
    args = parser.parse_args()
    errors = validate_package(as_of=args.as_of)
    if errors:
        print("Source governance validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Source governance validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
