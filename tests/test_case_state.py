import unittest
from dataclasses import dataclass, field
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references/case-state.md"


@dataclass
class CaseStateProbe:
    """Test-local probe of the U2 state contract; it is not a persistence layer."""

    case_id: str
    state: str = "Preflight"
    checkpoints: set[str] = field(default_factory=set)
    invalidated: set[str] = field(default_factory=set)
    deleted: bool = False
    unresolved_risks: set[str] = field(default_factory=set)

    def ensure_owner(self, requested_case_id: str) -> None:
        if requested_case_id != self.case_id:
            raise PermissionError("case ownership mismatch")
        if self.deleted:
            raise RuntimeError("deleted cases cannot be restored")

    def invalidate_for_material_change(self, reason: str) -> None:
        self.invalidated.update(self.checkpoints)
        self.checkpoints.clear()
        self.state = "Preflight"
        self.invalidated.add(reason)

    def record_negotiation_result(self, result: str) -> None:
        if self.state != "Negotiation":
            raise ValueError("negotiation result requires Negotiation state")
        if result not in {"rejected", "oral-only"}:
            raise ValueError("probe only covers unresolved negotiation outcomes")
        self.unresolved_risks.add(result)
        self.state = "Scanned"
        self.checkpoints.discard("decision")

    def delete(self, requested_case_id: str, receipt: str | None, host_delete_path: str | None) -> dict[str, str]:
        self.ensure_owner(requested_case_id)
        if receipt:
            self.deleted = True
            self.state = "Deleted"
            return {"scope": "skill-controlled-session-state", "receipt": receipt}
        if host_delete_path:
            return {"scope": "host-controlled-data", "host_delete_path": host_delete_path}
        raise RuntimeError("must not simulate a successful deletion")


class CaseStateContractTests(unittest.TestCase):
    def test_capability_change_invalidates_downstream_and_reverts_to_preflight(self) -> None:
        case = CaseStateProbe("case-a", state="Scanned", checkpoints={"material", "evidence", "decision"})
        case.invalidate_for_material_change("capability-version-changed")
        self.assertEqual("Preflight", case.state)
        self.assertFalse(case.checkpoints)
        self.assertTrue({"material", "evidence", "decision", "capability-version-changed"}.issubset(case.invalidated))

    def test_cross_case_read_recovery_and_deletion_fail_without_content_leakage(self) -> None:
        case_a = CaseStateProbe("case-a", checkpoints={"material"})
        for operation in (
            lambda: case_a.ensure_owner("case-b"),
            lambda: case_a.delete("case-b", "not-used", None),
        ):
            with self.assertRaises(PermissionError) as captured:
                operation()
            self.assertNotIn("case-a", str(captured.exception))
            self.assertNotIn("material", str(captured.exception))

    def test_deletion_returns_truthful_receipt_or_host_path_never_fake_success(self) -> None:
        deleted = CaseStateProbe("case-a")
        self.assertEqual(
            {"scope": "skill-controlled-session-state", "receipt": "receipt-123"},
            deleted.delete("case-a", "receipt-123", None),
        )
        with self.assertRaises(RuntimeError):
            deleted.ensure_owner("case-a")
        host_owned = CaseStateProbe("case-b")
        self.assertEqual(
            {"scope": "host-controlled-data", "host_delete_path": "host privacy controls"},
            host_owned.delete("case-b", None, "host privacy controls"),
        )
        with self.assertRaises(RuntimeError):
            host_owned.delete("case-b", None, None)

    def test_rejected_or_oral_negotiation_returns_to_scanned_and_recomputes(self) -> None:
        for result in ("rejected", "oral-only"):
            case = CaseStateProbe("case-a", state="Negotiation", checkpoints={"decision"})
            case.record_negotiation_result(result)
            self.assertEqual("Scanned", case.state)
            self.assertIn(result, case.unresolved_risks)
            self.assertNotIn("decision", case.checkpoints)

    def test_state_contract_requires_session_only_versioned_guards_and_nonfinal_close(self) -> None:
        contract = REFERENCE.read_text(encoding="utf-8")
        for required in (
            "CaseState v1", "Preflight", "AwaitingText", "AwaitingRedactedMaterial",
            "NonFinalClosed", "Deleted", "单次会话", "材料版本", "规则版本", "能力摘要",
            "禁止", "删除后", "口头", "Scanned",
        ):
            self.assertIn(required, contract)


if __name__ == "__main__":
    unittest.main()
