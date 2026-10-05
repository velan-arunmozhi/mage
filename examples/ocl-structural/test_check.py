"""Validate the interpreter and extraction boundary against known examples."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from check import BoundaryModel, HERE, check


class BoundaryTests(unittest.TestCase):
    def test_policy_truth_table_through_ocl(self):
        model = BoundaryModel((HERE / "boundary.ocl").read_text())
        cases = [
            ("api", "api", True), ("api", "service", True),
            ("api", "database", False), ("service", "api", True),
            ("service", "service", True), ("service", "database", True),
            ("database", "api", True), ("database", "service", True),
            ("database", "database", True),
        ]
        for source, target, expected in cases:
            with self.subTest(source=source, target=target):
                self.assertIs(model.evaluate_edge(source, target), expected)

    def test_valid_and_invalid_source_fixtures(self):
        valid = check(HERE / "fixtures/valid")
        invalid = check(HERE / "fixtures/invalid")
        self.assertEqual(valid["status"], "pass-within-scope")
        self.assertEqual(len(valid["results"]), 2)
        self.assertEqual(invalid["status"], "violations")
        self.assertEqual(len(invalid["violations"]), 1)
        violation = invalid["violations"][0]
        self.assertEqual((violation["from"], violation["to"]),
                         ("orders.api", "orders.database"))
        self.assertEqual(violation["evidence"]["symbol"],
                         "from database import save_order")
        self.assertEqual(violation["evidence"]["line"], 1)

    def test_rule_is_evaluated_rather_than_hardcoded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rule.ocl"
            path.write_text("context Dependency inv NoDirectApiDatabaseImport: "
                            "self.target.layer <> 'never'")
            report = check(HERE / "fixtures/invalid", rule_path=path)
            self.assertEqual(report["violations"], [])

    def test_unknown_import_and_unmodeled_file_are_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(HERE / "fixtures/valid", root, dirs_exist_ok=True)
            (root / "api.py").write_text("import other\n")
            (root / "other.py").write_text("import database\n")
            report = check(root)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["coverage"]["unmodeled_python_files"], ["other.py"])
            self.assertEqual(report["coverage"]["unresolved_imports"][0]["module"], "other")

    def test_source_change_is_reextracted_and_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(HERE / "fixtures/valid", root, dirs_exist_ok=True)
            before = check(root)
            (root / "api.py").write_text("import service\nimport database\n")
            after = check(root)
            self.assertNotEqual(before["components"][0]["sha256"],
                                after["components"][0]["sha256"])
            self.assertEqual(len(after["results"]), 3)
            self.assertEqual(len(after["violations"]), 1)

    def test_bad_ocl_is_an_error_even_without_observed_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for module in ("api", "service", "database"):
                (root / f"{module}.py").write_text("pass\n")
            rule = root / "broken.ocl"
            rule.write_text("context Dependency inv Broken: self.source.layer =")
            with self.assertRaises(Exception):
                check(root, rule_path=rule)

    def test_unknown_layer_is_not_treated_as_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            declarations = json.loads((HERE / "components.json").read_text())
            declarations["components"][0]["layer"] = "apis"
            manifest = Path(directory) / "components.json"
            manifest.write_text(json.dumps(declarations))
            with self.assertRaisesRegex(ValueError, "layers"):
                check(HERE / "fixtures/invalid", manifest=manifest)

    def test_cli_exit_codes_and_json(self):
        for fixture, code, status in [("valid", 0, "pass-within-scope"),
                                      ("invalid", 1, "violations"),
                                      ("missing", 2, "error")]:
            with self.subTest(fixture=fixture):
                result = subprocess.run(
                    [sys.executable, str(HERE / "check.py"),
                     str(HERE / "fixtures" / fixture)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], status)


if __name__ == "__main__":
    unittest.main()
