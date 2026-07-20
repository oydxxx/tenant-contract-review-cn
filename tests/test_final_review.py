import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPOSITORY_ROOT / "tests/fixtures/synthetic"
REFERENCES = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references"
FULL_REVIEW_INPUTS = {
    "main_contract",
    "cited_and_prior_annexes",
    "revised_pages",
    "supplements",
    "document_priority_agreement",
    "no_other_documents_confirmed",
}
PREFERENCE_CONFIRMATIONS = {
    "urgency", "total_cost", "alternatives", "paid_amounts", "risk_tolerance",
}
CONTACTS = {
    "landlord": "contractual-landlord",
    "agent": "agent-with-principal-channel",
    "broker": "broker-and-contract-party",
    "company": "company-contract-or-authority-channel",
}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def negotiation_card(finding: dict, user_selected: bool) -> dict:
    required = {
        "finding_id", "compatible_clause_text", "non_threatening_rationale",
        "linked_clause_ids", "linked_remedy_ids", "annex_ids", "document_priority_terms",
    }
    if finding.get("remediable") and not required <= finding.keys():
        raise ValueError("remediable finding requires a complete negotiation card")
    if finding.get("remediable") and (not finding["compatible_clause_text"] or not finding["non_threatening_rationale"]):
        raise ValueError("remediable finding cannot use an empty clause or rationale")
    conflict = bool(finding.get("conflicts"))
    return {
        "finding_id": finding["finding_id"],
        "coaching": "full" if finding.get("priority") == "high" or user_selected else "brief",
        "conflict_status": "coordinated_edit_required" if conflict else "clear",
        "direct_paste_prohibited": conflict,
        "linked_review_required": True,
    }


def concession_allowed(confirmations: dict) -> bool:
    return set(confirmations) == PREFERENCE_CONFIRMATIONS and all(confirmations.values())


def contact_route(counterparty_type: str, authority_verified: bool) -> dict:
    if counterparty_type not in CONTACTS:
        raise ValueError("unknown counterparty type")
    return {
        "contact": CONTACTS[counterparty_type],
        "authority_endpoint_reached": authority_verified,
        "must_request_authority_evidence": not authority_verified,
        "no_authority_promise": not authority_verified,
    }


def negotiation_response(starting_state: str, response: str, decision_checkpoint: str | None) -> dict:
    if starting_state != "Negotiation":
        raise ValueError("negotiation response requires Negotiation state")
    unresolved = response in {"rejected", "oral-only", "no-acceptable-written-remedy"}
    return {
        "state": "Scanned" if unresolved else "Negotiation",
        "risk_resolved": not unresolved,
        "decision_checkpoint": None if unresolved else decision_checkpoint,
        "recompute_outcome": unresolved,
    }


def final_review(submitted: dict, comparison_findings: list[dict]) -> dict:
    if not FULL_REVIEW_INPUTS <= submitted.keys():
        raise ValueError("full review protocol inputs are incomplete")
    missing = sorted(key for key in FULL_REVIEW_INPUTS if submitted[key] is not True)
    if missing:
        return {
            "state": "PartialFinalReview",
            "review_scope": "partial",
            "missing": missing,
            "final_conclusion": None,
        }
    material_change = any(
        finding.get("changed") or finding.get("priority") == "high" or finding.get("kind") == "new_high_penalty"
        for finding in comparison_findings
    )
    if material_change:
        return {
            "state": "Negotiation",
            "review_scope": "global",
            "missing": [],
            "final_conclusion": None,
        }
    return {
        "state": "GlobalFinalReview",
        "review_scope": "global",
        "missing": [],
        "final_conclusion": "eligible-only-after-current-decision-guards",
    }


class FinalReviewContractTests(unittest.TestCase):
    def test_1_every_remediable_finding_has_compatible_text_rationale_and_limited_coaching(self) -> None:
        record = fixture("negotiation-remedy.json")
        card = negotiation_card(record["finding"], record["user_selected"])
        self.assertEqual("brief", card["coaching"])
        self.assertFalse(card["direct_paste_prohibited"])
        selected = negotiation_card(record["finding"], True)
        self.assertEqual("full", selected["coaching"])
        high = dict(record["finding"], priority="high")
        self.assertEqual("full", negotiation_card(high, False)["coaching"])
        incomplete = dict(record["finding"])
        del incomplete["compatible_clause_text"]
        with self.assertRaises(ValueError):
            negotiation_card(incomplete, False)

    def test_2_conflicts_require_coordinated_edit_after_all_linked_material_is_checked(self) -> None:
        record = fixture("negotiation-conflict.json")
        card = negotiation_card(record["finding"], record["user_selected"])
        self.assertEqual("coordinated_edit_required", card["conflict_status"])
        self.assertTrue(card["direct_paste_prohibited"])
        self.assertTrue(card["linked_review_required"])
        for field in ("linked_clause_ids", "linked_remedy_ids", "annex_ids", "document_priority_terms"):
            self.assertTrue(record["finding"][field])

    def test_3_contact_and_escalation_follow_identity_without_promising_authority(self) -> None:
        record = fixture("negotiation-contact.json")
        for identity in record["identity_cases"]:
            route = contact_route(identity["counterparty_type"], identity["authority_verified"])
            self.assertTrue(route["contact"])
            self.assertTrue(route["must_request_authority_evidence"])
            self.assertTrue(route["no_authority_promise"])
            self.assertFalse(route["authority_endpoint_reached"])

    def test_4_preference_concession_needs_all_five_current_user_confirmations(self) -> None:
        record = fixture("negotiation-preference.json")
        self.assertFalse(concession_allowed(record["preference_concession"]))
        confirmed = {field: True for field in PREFERENCE_CONFIRMATIONS}
        self.assertTrue(concession_allowed(confirmed))
        self.assertFalse(concession_allowed({"urgency": True}))

    def test_5_oral_or_rejected_response_returns_to_scanned_and_invalidates_decision(self) -> None:
        record = fixture("negotiation-oral.json")
        result = negotiation_response(record["starting_state"], record["response"], record["decision_checkpoint"])
        self.assertEqual("Scanned", result["state"])
        self.assertFalse(result["risk_resolved"])
        self.assertIsNone(result["decision_checkpoint"])
        self.assertTrue(result["recompute_outcome"])

    def test_6_incomplete_global_protocol_is_partial_review_only(self) -> None:
        record = fixture("negotiation-partial-final.json")
        result = final_review(record["submitted"], [])
        self.assertEqual("PartialFinalReview", result["state"])
        self.assertEqual("partial", result["review_scope"])
        self.assertIsNone(result["final_conclusion"])
        self.assertEqual(
            {"cited_and_prior_annexes", "supplements", "no_other_documents_confirmed"},
            set(result["missing"]),
        )

    def test_7_synthetic_end_to_end_scan_to_global_review_returns_to_negotiation_on_new_high_penalty(self) -> None:
        record = fixture("negotiation-end-to-end.json")
        self.assertEqual("Scanned", record["starting_state"])
        result = final_review(record["submitted"], record["comparison_findings"])
        self.assertEqual("global", result["review_scope"])
        self.assertEqual("Negotiation", result["state"])
        self.assertIsNone(result["final_conclusion"])

    def test_references_preserve_final_review_protocol_and_talk_track_boundaries(self) -> None:
        playbook = (REFERENCES / "negotiation-playbook.md").read_text(encoding="utf-8")
        workflow = (REFERENCES / "workflow.md").read_text(encoding="utf-8")
        output = (REFERENCES / "output-contract.md").read_text(encoding="utf-8")
        combined = playbook + workflow + output
        for required in (
            "compatible_clause_text", "non_threatening_rationale", "coordinated_edit_required",
            "direct_paste_prohibited", "urgency", "total_cost", "alternatives", "paid_amounts",
            "risk_tolerance", "口头承诺", "cited_and_prior_annexes", "没有其他相关文件",
            "PartialFinalReview", "GlobalFinalReview", "新增高额违约责任", "不替代律师",
        ):
            self.assertIn(required, combined)


if __name__ == "__main__":
    unittest.main()
