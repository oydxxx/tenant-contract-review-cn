import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references/host-capabilities.md"
PRIVACY_REFERENCE = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references/privacy-safety.md"
FIXTURE = REPOSITORY_ROOT / "tests/fixtures/synthetic/host-capabilities.json"
NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)
FILE_SECURITY_KEYS = {
    "real_type_identification",
    "resource_limits",
    "isolated_parsing",
    "dangerous_content_disabled",
}
PRIVACY_KEYS = {
    "encryption",
    "case_access_control",
    "ordinary_log_exclusion",
    "retention_and_backup_deletion",
    "user_deletion",
    "third_party_disclosure",
}


def is_current_supported(record: object, now: datetime = NOW) -> bool:
    """Test-local interpretation of the U2 host declaration contract."""
    if not isinstance(record, dict) or record.get("status") != "supported":
        return False
    for field in ("provider", "verification", "verified_at", "expires_at"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            return False
    try:
        return datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00")) > now
    except ValueError:
        return False


def gate(capabilities: dict, *, attachment_already_in_host: bool = False) -> dict[str, str]:
    file_safe = all(is_current_supported(capabilities.get("file_security", {}).get(key)) for key in FILE_SECURITY_KEYS)
    privacy_safe = all(is_current_supported(capabilities.get("privacy", {}).get(key)) for key in PRIVACY_KEYS)
    if attachment_already_in_host:
        return {"channel": "do-not-read", "boundary": "host-copy-already-exists"}
    if not file_safe:
        return {"channel": "redacted-pasted-text-only", "boundary": "file-security-not-verified"}
    if not privacy_safe:
        return {"channel": "redacted-attachments-only", "boundary": "privacy-not-verified"}
    return {"channel": "real-materials", "boundary": "both-gates-verified"}


class HostCapabilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.capabilities = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_unknown_file_safety_allows_only_redacted_pasted_text(self) -> None:
        capabilities = copy.deepcopy(self.capabilities)
        capabilities["file_security"]["isolated_parsing"]["status"] = "unknown"
        self.assertEqual("redacted-pasted-text-only", gate(capabilities)["channel"])

    def test_incomplete_privacy_allows_only_redacted_attachments_and_disclosure(self) -> None:
        capabilities = copy.deepcopy(self.capabilities)
        capabilities["privacy"]["ordinary_log_exclusion"]["status"] = "unknown"
        self.assertEqual("redacted-attachments-only", gate(capabilities)["channel"])
        self.assertEqual("privacy-not-verified", gate(capabilities)["boundary"])

    def test_both_current_gates_allow_real_materials_only_then(self) -> None:
        self.assertEqual("real-materials", gate(self.capabilities)["channel"])

    def test_attachment_already_in_host_is_not_read_and_host_copy_is_disclosed(self) -> None:
        outcome = gate(self.capabilities, attachment_already_in_host=True)
        self.assertEqual({"channel": "do-not-read", "boundary": "host-copy-already-exists"}, outcome)

    def test_expired_or_changed_declaration_returns_to_preflight_gate(self) -> None:
        capabilities = copy.deepcopy(self.capabilities)
        capabilities["privacy"]["user_deletion"]["expires_at"] = "2026-07-19T23:59:59Z"
        self.assertEqual("redacted-attachments-only", gate(capabilities)["channel"])
        capabilities["file_security"]["isolated_parsing"]["status"] = "unsupported"
        self.assertEqual("redacted-pasted-text-only", gate(capabilities)["channel"])

    def test_contract_documents_fail_closed_and_disclose_host_ownership(self) -> None:
        host_contract = REFERENCE.read_text(encoding="utf-8")
        privacy_contract = PRIVACY_REFERENCE.read_text(encoding="utf-8")
        for required in ("unknown", "unsupported", "充分脱敏", "宿主", "不得读取", "provider", "verification", "expires_at"):
            self.assertIn(required, host_contract)
        for required in ("会话", "审计", "备份", "不能承诺", "删除"):
            self.assertIn(required, privacy_contract)


if __name__ == "__main__":
    unittest.main()
