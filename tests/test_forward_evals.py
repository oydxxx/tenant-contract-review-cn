import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY_ROOT / "scripts/run_forward_evals.py"
CASES = REPOSITORY_ROOT / "tests/forward-evals"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_forward_evals", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ForwardEvaluationTests(unittest.TestCase):
    def test_synthetic_suite_is_complete_deterministic_and_reports_hard_gates(self) -> None:
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.json"
            second = Path(temporary) / "second.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, runner.run(CASES, first))
                self.assertEqual(0, runner.run(CASES, second))
            first_report = json.loads(first.read_text(encoding="utf-8"))
            second_report = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(first_report, second_report)
        self.assertEqual("tenant-contract-review-cn-forward-eval/v1", first_report["report_version"])
        self.assertEqual(set(range(1, 15)), set(first_report["acceptance_examples_covered"]))
        self.assertEqual(1.0, first_report["hard_gate_pass_rate"])
        self.assertEqual([], first_report["hard_gate_failures"])
        self.assertTrue(first_report["manual_review_needed"])
        self.assertEqual(14, first_report["case_count"])

    def test_missing_synthetic_marker_is_a_hard_failure(self) -> None:
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temporary:
            cases = Path(temporary) / "cases"
            cases.mkdir()
            (cases / "invalid.json").write_text(
                json.dumps({"case_id": "invalid", "acceptance_examples": [1]}), encoding="utf-8"
            )
            output = Path(temporary) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(1, runner.run(cases, output))
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(0.0, report["hard_gate_pass_rate"])
        self.assertIn("fixture_contract", report["failure_categories"])


if __name__ == "__main__":
    unittest.main()
