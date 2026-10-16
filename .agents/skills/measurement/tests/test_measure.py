"""Exercise quantitative claims and failure cases with synthetic evidence only."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from measure import evaluate, load


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load(ROOT / "examples" / "four-chains.json")

    def observation(self, condition="mage", metric="reconstruction.files-read"):
        return next(item for item in self.bundle["observations"]
                    if item["id"] == metric + "." + condition)

    def definition(self, metric="reconstruction.files-read"):
        return next(item for item in self.bundle["definitions"] if item["id"] == metric)

    def result(self, metric="reconstruction.files-read"):
        return next(item for item in evaluate(self.bundle)["results"]
                    if item["measurement_id"] == metric)

    def test_four_primary_outcomes_have_independent_expected_values(self):
        report = evaluate(self.bundle)
        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["synthetic"])
        rows = {row["measurement_id"]: row for row in report["results"]}
        self.assertAlmostEqual(rows["correctness.acceptance"]["delta"], 0.1)
        self.assertAlmostEqual(rows["durability.rework"]["delta"], -0.1)
        self.assertEqual(rows["reconstruction.files-read"]["observed_value"], 4)
        self.assertEqual(rows["reconstruction.files-read"]["reference_value"], 6)
        self.assertEqual(rows["reconstruction.files-read"]["delta"], -2)
        self.assertAlmostEqual(rows["quality.defect-escape"]["delta"], -0.125)

    def test_all_matching_controls_are_checked(self):
        changes = {"repository": "other-repo", "revision": "other-revision",
                   "task": "other-task", "harness": "other-harness",
                   "foundation_model": "other-model", "tool_access": ["read"],
                   "resource_limits": {"wall_time_seconds": 12},
                   "retry_policy": "unlimited"}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.setUp()
                if field == "repository":
                    # Each definition retains its own scope; the baseline can still
                    # be individually valid while ineligible for this comparison.
                    other = deepcopy(self.definition())
                    other["id"] = "other.definition"
                    other["scope"]["repository"] = value
                    self.bundle["definitions"].append(other)
                    self.observation("baseline")["definition_id"] = other["id"]
                self.observation("baseline")["context"][field] = value
                self.assertEqual(self.result()["status"], "not_comparable")

    def test_missing_controls_do_not_match_each_other(self):
        for condition in ("mage", "baseline"):
            self.observation(condition)["context"]["revision"] = "unknown"
        row = self.result()
        self.assertEqual(row["status"], "unknown")
        self.assertIn("unknown_context:revision", row["reasons"])

    def test_tool_order_is_not_a_changed_treatment(self):
        self.observation("baseline")["context"]["tool_access"].reverse()
        self.assertEqual(self.result()["status"], "lower_than_reference")

    def test_definition_changes_prevent_comparison(self):
        for field, value in (("unit", "seconds"), ("denominator", "attempted_tasks"),
                             ("time_window", {"start": "run_started", "end": "run_ended"}),
                             ("filters", {"include": ["other-events"], "exclude": []})):
            with self.subTest(field=field):
                self.setUp()
                metric = "durability.rework"
                definition = deepcopy(self.definition(metric))
                definition["id"] = "baseline.definition"
                definition["quantity"][field] = value
                self.bundle["definitions"].append(definition)
                observation = self.observation("baseline", metric)
                observation["definition_id"] = definition["id"]
                if field == "unit":
                    observation["unit"] = value
                self.assertEqual(self.result(metric)["status"], "not_comparable")

    def test_missing_samples_are_visible_and_policy_is_explicit(self):
        observation = self.observation()
        observation["inputs"]["samples"].append("unknown")
        observation["value"] = "unknown"
        self.assertEqual(self.result()["status"], "unknown")
        self.assertEqual(self.result()["missingness"]["observation"], 1)
        self.definition()["missing_data"]["policy"] = "exclude_and_report"
        observation["value"] = 4
        self.assertEqual(self.result()["observed_value"], 4)
        self.assertEqual(self.result()["missingness"]["observation"], 1)

    def test_zero_is_not_a_substitute_for_missing_stale_or_invalid_evidence(self):
        for state in ("missing", "stale", "invalid"):
            with self.subTest(state=state):
                self.setUp()
                observation = self.observation()
                observation["evidence_state"] = state
                observation["value"] = "unknown"
                self.assertEqual(self.result()["status"], "unknown")
                observation["value"] = 0
                with self.assertRaisesRegex(ValueError, "does not match"):
                    evaluate(self.bundle)

    def test_unknown_without_evidence_is_not_a_success(self):
        observation = self.observation()
        observation["evidence_refs"] = []
        observation["value"] = "unknown"
        self.assertEqual(evaluate(self.bundle)["status"], "incomplete")

    def test_zero_denominator_is_unknown_even_with_exclusion_policy(self):
        metric = "correctness.acceptance"
        observation = self.observation(metric=metric)
        observation["inputs"] = {"numerator": 0, "denominator": 0}
        observation["value"] = "unknown"
        self.definition(metric)["missing_data"]["policy"] = "exclude_and_report"
        self.assertEqual(self.result(metric)["status"], "unknown")

    def test_zero_baseline_preserves_delta_without_inventing_relative_change(self):
        observation = self.observation("baseline")
        observation["inputs"]["samples"] = []
        observation["value"] = 0
        row = self.result()
        self.assertEqual(row["delta"], 4)
        self.assertEqual(row["relative_delta"], "unknown")

    def test_numeric_aggregations_and_empty_evidence(self):
        cases = [("value", [7], 7), ("sum", [2, 3, 3], 8),
                 ("mean", [2, 3, 7], 4), ("count", ["a", "a", "b"], 3),
                 ("count_distinct", ["a", "a", "b"], 2),
                 ("sum", [], 0), ("count", [], 0), ("mean", [], "unknown")]
        for aggregation, samples, expected in cases:
            with self.subTest(aggregation=aggregation, samples=samples):
                self.setUp()
                self.definition()["quantity"]["aggregation"] = aggregation
                for condition in ("baseline", "mage"):
                    observation = self.observation(condition)
                    observation["inputs"] = {"samples": samples}
                    observation["value"] = expected
                self.assertEqual(self.result()["observed_value"], expected)

    def test_bound_margins_and_tolerance_do_not_install_policy(self):
        reference = next(item for item in self.bundle["references"]
                         if item["definition_id"] == "reconstruction.files-read")
        reference.pop("observation_id")
        cases = [("upper_bound", 3, 0, "outside_bound", -1),
                 ("upper_bound", 3, 1, "within_bound", -1),
                 ("lower_bound", 5, 0, "outside_bound", -1),
                 ("target_range", {"lower": 3, "upper": 5}, 0, "within_range", 1),
                 ("target_range", {"lower": 5, "upper": 6}, 0, "outside_range", -1)]
        for kind, value, tolerance, status, margin in cases:
            with self.subTest(kind=kind, tolerance=tolerance):
                reference.update(kind=kind, value=value, tolerance=tolerance)
                row = self.result()
                self.assertEqual(row["status"], status)
                self.assertEqual(row["margin_to_bound"], margin)
                self.assertEqual(evaluate(self.bundle)["status"], "complete")

    def test_unknown_tolerance_preserves_the_arithmetic(self):
        self.bundle["references"][2]["tolerance"] = "unknown"
        row = self.result()
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["delta"], -2)

    def test_bad_records_and_false_arithmetic_are_rejected(self):
        for case in ("wrong_value", "boolean", "unit", "duplicate", "dangling",
                     "timestamp", "negative_tolerance", "nonfinite", "unknown_aggregation"):
            with self.subTest(case=case):
                self.setUp()
                observation = self.observation()
                if case == "wrong_value":
                    observation["value"] = 99
                elif case == "boolean":
                    observation["value"] = True
                elif case == "unit":
                    observation["unit"] = "seconds"
                elif case == "duplicate":
                    self.bundle["observations"].append(deepcopy(observation))
                elif case == "dangling":
                    self.bundle["comparisons"][0]["reference_id"] = "missing"
                elif case == "timestamp":
                    observation["observed_at"] = "yesterday"
                elif case == "negative_tolerance":
                    self.bundle["references"][0]["tolerance"] = -1
                elif case == "nonfinite":
                    observation["value"] = float("nan")
                else:
                    self.definition()["quantity"]["aggregation"] = "eval(expression)"
                with self.assertRaises(ValueError):
                    evaluate(self.bundle)

    def test_unapproved_composites_and_duplicate_json_keys_are_not_accepted(self):
        self.definition()["quantity"]["aggregation"] = "weighted_sum"
        with self.assertRaises(ValueError):
            evaluate(self.bundle)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"value": 1, "value": 2}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                load(path)

    def test_no_checks_does_not_mean_complete(self):
        self.bundle["comparisons"] = []
        self.assertEqual(evaluate(self.bundle)["status"], "incomplete")

    def test_cli_recomputes_saved_report_and_returns_meaningful_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle.json"
            report_path = Path(directory) / "report.json"
            script = str(ROOT / "scripts" / "measure.py")

            def run(*extra):
                return subprocess.run([sys.executable, script, str(bundle), *extra],
                                      capture_output=True, text=True)

            bundle.write_text(json.dumps(self.bundle))
            completed = run()
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report_path.write_text(completed.stdout)
            self.assertEqual(run("--verify-report", str(report_path)).returncode, 0)
            report = json.loads(completed.stdout)
            report["schema_version"] = True
            report_path.write_text(json.dumps(report))
            self.assertEqual(run("--verify-report", str(report_path)).returncode, 2)
            report = json.loads(completed.stdout)
            report["results"][0]["delta"] = -999
            report_path.write_text(json.dumps(report))
            self.assertEqual(run("--verify-report", str(report_path)).returncode, 2)
            self.observation()["value"] = "unknown"
            self.observation()["evidence_state"] = "missing"
            bundle.write_text(json.dumps(self.bundle))
            self.assertEqual(run().returncode, 1)
            self.observation()["value"] = 0
            bundle.write_text(json.dumps(self.bundle))
            invalid = run()
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(json.loads(invalid.stdout)["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
