import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/scripts/validate_sources.py"
SPEC = importlib.util.spec_from_file_location("validate_sources", SCRIPT_PATH)
assert SPEC and SPEC.loader
validate_sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_sources)


class SourceGovernanceTests(unittest.TestCase):
    def current_legal_record(self) -> dict[str, object]:
        return {
            "id": "TEST-CURRENT",
            "source_kind": "legal_basis",
            "authority_category": "local_regulation",
            "publisher": "Official publisher",
            "final_domain": "example.gov.cn",
            "source_url": "https://example.gov.cn/rules/current",
            "final_url_verified": True,
            "redirect_chain": [],
            "scope": {
                "geography": "Example City",
                "effective_from": "2026-01-01",
                "effective_to": None,
                "subjects": ["tenant"],
                "topics": ["residential leasing"],
            },
            "reviewed_on": "2026-07-20",
            "review_due_on": "2026-10-20",
            "status": "current",
            "risk_propositions": ["A verified local rule supports only scoped legal information."],
        }

    def test_non_official_repost_summary_and_redirect_are_not_legal_basis(self) -> None:
        for url, domain, verified in (
            ("https://news.example.com/repost", "news.example.com", True),
            ("https://example.gov.cn/search-summary", "example.gov.cn", False),
            ("https://redirect.example.gov.cn/?next=https://example.gov.cn", "example.gov.cn", True),
        ):
            record = self.current_legal_record()
            record.update(source_url=url, final_domain=domain, final_url_verified=verified)
            self.assertEqual("requires_fresh_review", validate_sources.legal_conclusion_status(record, date(2026, 7, 20)))
        record = self.current_legal_record()
        record["redirect_chain"] = ["https://example.gov.cn/interstitial"]
        self.assertEqual("requires_fresh_review", validate_sources.legal_conclusion_status(record, date(2026, 7, 20)))

    def test_expired_withdrawn_conflicting_or_incomplete_rules_downgrade(self) -> None:
        for change in (
            {"review_due_on": "2026-07-19"},
            {"status": "withdrawn"},
            {"status": "conflicting"},
            {"scope": {"geography": "Example City"}},
        ):
            record = self.current_legal_record()
            record.update(change)
            self.assertEqual("requires_fresh_review", validate_sources.legal_conclusion_status(record, date(2026, 7, 20)))

    def test_model_text_can_only_support_structure_or_drafting(self) -> None:
        model = self.current_legal_record()
        model["source_kind"] = "structural_reference"
        model["authority_category"] = "model_text"
        self.assertEqual("not_legal_basis", validate_sources.legal_conclusion_status(model, date(2026, 7, 20)))

    def test_single_community_post_stays_out_of_red_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            for filename in ("national-rules.yaml", "city-beijing.yaml", "city-shanghai.yaml", "city-guangzhou.yaml", "city-shenzhen.yaml", "red-lines.yaml", "community-scenarios.yaml"):
                (package / filename).write_text((REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references" / filename).read_text(encoding="utf-8"), encoding="utf-8")
            community = validate_sources.load_yaml(package / "community-scenarios.yaml")
            community["records"][0]["source_kind"] = "red_line"
            community["records"][0]["independent_source"] = "知乎 tenant-point experience"
            import yaml
            (package / "community-scenarios.yaml").write_text(yaml.safe_dump(community, allow_unicode=True), encoding="utf-8")
            self.assertTrue(any("candidate_scenario" in error for error in validate_sources.validate_package(package)))

    def test_personal_blacklist_unverified_accusation_or_long_copy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            for filename in ("national-rules.yaml", "city-beijing.yaml", "city-shanghai.yaml", "city-guangzhou.yaml", "city-shenzhen.yaml", "red-lines.yaml", "community-scenarios.yaml"):
                (package / filename).write_text((REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references" / filename).read_text(encoding="utf-8"), encoding="utf-8")
            candidate_document = validate_sources.load_yaml(package / "community-scenarios.yaml")
            candidate_document["records"][0]["independent_source"] = "未经证实的企业黑名单：张三，身份证 " + "110105" + "19491231002X"
            candidate_document["records"][0]["mechanism"] = "x" * 600
            import yaml
            (package / "community-scenarios.yaml").write_text(yaml.safe_dump(candidate_document, allow_unicode=True), encoding="utf-8")
            errors = validate_sources.validate_package(package)
            self.assertTrue(any("prohibited" in error for error in errors))
            self.assertTrue(any("overlong" in error for error in errors))

    def test_other_cities_use_national_base_and_disclose_local_gap(self) -> None:
        for city in ("Wuhan", "Chengdu", "Hangzhou"):
            self.assertEqual("coverage_gap", validate_sources.city_coverage({}, city))
        shenzhen = validate_sources.load_yaml(REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references/city-shenzhen.yaml")
        self.assertEqual("coverage_gap", validate_sources.city_coverage(shenzhen, "Shenzhen"))
        self.assertTrue(shenzhen["coverage_gap"])

    def test_effective_window_and_review_due_date_are_checked_against_requested_date(self) -> None:
        record = self.current_legal_record()
        record["scope"]["effective_from"] = "2026-07-21"
        self.assertEqual("requires_fresh_review", validate_sources.legal_conclusion_status(record, date(2026, 7, 20)))
        record["scope"]["effective_from"] = "2026-01-01"
        record["scope"]["effective_to"] = "2026-07-19"
        self.assertEqual("requires_fresh_review", validate_sources.legal_conclusion_status(record, date(2026, 7, 20)))
        record["scope"]["effective_to"] = None
        record["review_due_on"] = "2026-07-19"
        self.assertEqual("requires_fresh_review", validate_sources.legal_conclusion_status(record, date(2026, 7, 20)))

    def test_realtime_queries_reject_case_personal_and_contract_data(self) -> None:
        self.assertTrue(validate_sources.is_safe_realtime_query("广州市 住房租赁 备案 现行 规定"))
        for query in (
            "张三 北京市朝阳区某小区 1号楼 住房租赁规定",
            "身份证 " + "110105" + "19491231002X 租赁规定",
            "账号 6222020202020202 租赁规定",
            "合同第 12 条原句 租赁规定",
        ):
            self.assertFalse(validate_sources.is_safe_realtime_query(query))

    def test_repository_package_is_valid(self) -> None:
        self.assertEqual([], validate_sources.validate_package())


if __name__ == "__main__":
    unittest.main()
