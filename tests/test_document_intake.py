import json
import unittest
from dataclasses import dataclass, field
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIRECTORY = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references"
FIXTURES = REPOSITORY_ROOT / "tests/fixtures/synthetic"
FILE_SECURITY_KEYS = {
    "real_type_verified",
    "size_page_time_within_limit",
    "isolated_parse",
    "pdf_script_disabled",
    "embedded_files_disabled",
    "automatic_external_links_disabled",
    "automatic_network_access_disabled",
    "compression_bomb_blocked",
}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def intake_gate(record: dict) -> dict[str, object]:
    safe = record.get("parse_status") == "complete" and all(
        record.get("file_security", {}).get(key) is True for key in FILE_SECURITY_KEYS
    )
    if safe:
        return {"read_content": True, "state": "Extraction", "reason": None}
    return {
        "read_content": False,
        "state": "AwaitingMaterial",
        "reason": "host-security-or-parse-status-not-acceptable",
    }


def quality_coverage(pages: list[dict], expected_attachments: list[str]) -> dict[str, list[object]]:
    printed_numbers = []
    issues: list[str] = []
    for page in pages:
        label = page["printed_page_label"]
        number, total = (int(part) for part in label.split("/"))
        printed_numbers.append(number)
        if page["duplicate_of"]:
            issues.append(f"duplicate:{page['page_record_id']}")
        if page["rotation_degrees"] % 360:
            issues.append(f"rotation:{page['page_record_id']}")
        if page["crop_or_obscuration"] != "none":
            issues.append(f"crop:{page['page_record_id']}")
        if page["legibility"] in {"low", "unreadable"}:
            issues.append(f"legibility:{page['page_record_id']}")
        if page["seal_or_signature_status"] in {"expected-missing", "unclear"}:
            issues.append(f"seal:{page['page_record_id']}")
    expected_pages = set(range(1, total + 1)) if pages else set()
    missing_pages = sorted(expected_pages.difference(printed_numbers))
    return {
        "covered_pages": sorted(set(printed_numbers)),
        "missing_pages": missing_pages,
        "issues": issues,
        "missing_attachments": expected_attachments,
    }


def high_impact_field_status(record: dict, user_confirmation: str | None = None) -> dict[str, str]:
    conflict = record["ocr_candidate"] != record["visible_candidate"]
    source_reliability = record["source_reliability"]
    confirmation = user_confirmation or record["transcription_confirmation"]
    final_blocked = conflict or record["ocr_confidence"] < 0.8 or source_reliability != "high"
    return {
        "transcription_confirmation": confirmation,
        "source_reliability": source_reliability,
        "final_decision": "blocked" if final_blocked else "eligible",
    }


@dataclass
class MaterialVersionProbe:
    inventory_version: str
    content_fingerprint: str
    active: set[str] = field(default_factory=lambda: {"field", "evidence", "finding", "decision", "negotiation"})

    def replace_page(self, fingerprint: str) -> None:
        if fingerprint == self.content_fingerprint:
            return
        self.inventory_version = f"{self.inventory_version}-next"
        self.content_fingerprint = fingerprint
        self.active.clear()


def nonfinal_close(record: dict) -> dict[str, object]:
    return {
        "state": "NonFinalClosed",
        "covered_pages": record["covered_pages"],
        "unknowns": record["refused"],
        "findings": record["current_nonfinal_findings"],
        "final_conclusion": None,
        "deletion_entry": record["deletion_entry"],
    }


class DocumentIntakeContractTests(unittest.TestCase):
    def test_dangerous_or_failed_file_is_blocked_before_content_reaches_model(self) -> None:
        dangerous = fixture("intake-dangerous-file.json")
        self.assertTrue(dangerous["synthetic"])
        outcome = intake_gate(dangerous)
        self.assertFalse(outcome["read_content"])
        self.assertEqual("AwaitingMaterial", outcome["state"])
        self.assertEqual("host-security-or-parse-status-not-acceptable", outcome["reason"])

    def test_page_quality_issues_produce_coverage_and_specific_reupload_list(self) -> None:
        record = fixture("intake-quality-issues.json")
        coverage = quality_coverage(record["pages"], record["attachment_ids_expected"])
        self.assertEqual([1, 3], coverage["covered_pages"])
        self.assertEqual([2, 4], coverage["missing_pages"])
        self.assertEqual(["annex-a"], coverage["missing_attachments"])
        for issue in ("duplicate:p3-copy", "rotation:p3", "crop:p3", "legibility:p3", "seal:p3"):
            self.assertIn(issue, coverage["issues"])

    def test_conflicting_ocr_key_field_cannot_enter_final_decision_before_confirmation_and_reliable_source(self) -> None:
        record = fixture("intake-ocr-conflict.json")
        before = high_impact_field_status(record)
        after_confirmation = high_impact_field_status(record, user_confirmation="confirmed")
        self.assertEqual("unconfirmed", before["transcription_confirmation"])
        self.assertEqual("confirmed", after_confirmation["transcription_confirmation"])
        self.assertEqual("low", after_confirmation["source_reliability"])
        self.assertEqual("blocked", before["final_decision"])
        self.assertEqual("blocked", after_confirmation["final_decision"])

    def test_replacement_invalidates_old_fingerprint_dependents(self) -> None:
        record = fixture("intake-replacement.json")
        probe = MaterialVersionProbe(record["old_material_inventory_version"], record["old_content_fingerprint"])
        probe.replace_page(record["replacement"]["content_fingerprint"])
        self.assertEqual("inventory-v1-next", probe.inventory_version)
        self.assertFalse(probe.active)
        self.assertNotEqual(record["old_content_fingerprint"], probe.content_fingerprint)

    def test_role_requests_are_minimal_and_never_default_to_full_identity_or_title_documents(self) -> None:
        record = fixture("intake-role-evidence.json")
        requested = set(record["requested_fields"])
        forbidden = set(record["forbidden_fields"])
        self.assertTrue({"principal_name", "authority_scope", "payee_contract_relation", "payment_basis"}.issubset(requested))
        self.assertFalse(requested.intersection(forbidden))
        self.assertEqual({"agent-signing-authority", "actual-payee"}, set(record["unknown_roles"]))

    def test_refusal_closes_with_scoped_nonfinal_report_and_real_deletion_entry(self) -> None:
        report = nonfinal_close(fixture("intake-refusal.json"))
        self.assertEqual("NonFinalClosed", report["state"])
        self.assertEqual([1, 3], report["covered_pages"])
        self.assertTrue(report["unknowns"])
        self.assertTrue(report["findings"])
        self.assertIsNone(report["final_conclusion"])
        self.assertEqual("skill-controlled-session-state", report["deletion_entry"])

    def test_references_preserve_structured_page_evidence_and_nonfinal_boundary(self) -> None:
        document_intake = (REFERENCE_DIRECTORY / "document-intake.md").read_text(encoding="utf-8")
        matrix = (REFERENCE_DIRECTORY / "evidence-matrix.md").read_text(encoding="utf-8")
        workflow = (REFERENCE_DIRECTORY / "workflow.md").read_text(encoding="utf-8")
        for required in (
            "true_type", "isolated_parse", "pdf_script_disabled", "embedded_files_disabled",
            "automatic_external_links_disabled", "compression_bomb_blocked", "physical_order",
            "duplicate_of", "rotation_degrees", "crop_or_obscuration", "seal_or_signature_status",
            "ocr_blocks", "material_inventory_version", "内容指纹", "transcription_confirmation",
            "source_reliability", "NonFinalClosed", "不得形成最终签约或劝退结论",
        ):
            self.assertIn(required, document_intake)
        for required in ("出租权", "代理签约权", "转租权", "实际收款权", "完整身份证", "完整权属"):
            self.assertIn(required, matrix)
        for required in ("不可信数据", "版本守卫", "NonFinalClosed", "不得继续推断"):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
