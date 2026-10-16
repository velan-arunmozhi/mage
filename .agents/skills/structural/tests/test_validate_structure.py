"""Check actual extraction, source evidence, and fail-closed interpreter behavior."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts/validate_structure.py"
spec = importlib.util.spec_from_file_location("structural_ocl", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class StructuralOclTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        self.root = self.workspace / "src"
        self.root.mkdir()
        self.manifest = self.workspace / "components.json"
        self.rule = self.workspace / "boundary.ocl"
        shutil.copy(SKILL / "assets/boundary.example.ocl", self.rule)
        self.components = [
            {"id": "orders.api", "module": "orders.api", "path": "orders/api.py", "layer": "api"},
            {"id": "orders.service", "module": "orders.service", "path": "orders/service.py", "layer": "service"},
            {"id": "orders.database", "module": "orders.database", "path": "orders/database.py", "layer": "database"},
            {"id": "orders.package", "module": "orders", "path": "orders/__init__.py", "layer": "service"},
        ]
        (self.root / "orders").mkdir()
        self.write("orders/api.py", "from .service import place_order\n")
        self.write("orders/service.py", "from orders.database import save_order\n")
        self.write("orders/database.py", "def save_order(): pass\n")
        self.write("orders/__init__.py", "pass\n")
        self.declare()

    def write(self, path, text):
        (self.root / path).write_text(text)

    def declare(self, **extra):
        self.manifest.write_text(json.dumps({"components": self.components, **extra}))

    def check(self):
        return checker.check(self.root, self.manifest, self.rule, "demo: test authority")

    def test_policy_truth_table_through_interpreter(self):
        model = checker.BoundaryModel(self.rule.read_text())
        for source in ("api", "service", "database"):
            for target in ("api", "service", "database"):
                with self.subTest(source=source, target=target):
                    self.assertIs(model.evaluate_edge(source, target),
                                  not (source == "api" and target == "database"))

    def test_package_source_evidence_and_violation(self):
        valid = self.check()
        self.assertEqual(valid["status"], "pass-within-scope")
        self.assertEqual(len(valid["results"]), 2)
        self.write("orders/api.py", "from .database import save_order\n")
        invalid = self.check()
        self.assertEqual(invalid["status"], "violations")
        edge = invalid["violations"][0]
        self.assertEqual((edge["from"], edge["to"]), ("orders.api", "orders.database"))
        self.assertEqual(edge["evidence"]["symbol"], "from .database import save_order")
        self.assertEqual(edge["evidence"]["line"], 1)
        self.assertNotEqual(valid["components"][0]["sha256"], invalid["components"][0]["sha256"])

    def test_qualified_and_child_imports(self):
        for statement in ("import orders.database", "from orders import database", "from . import database"):
            with self.subTest(statement=statement):
                self.write("orders/api.py", statement + "\n")
                self.assertEqual(self.check()["violations"][0]["to"], "orders.database")

    def test_nested_package_relative_import(self):
        (self.root / "orders/web").mkdir()
        self.components[0].update(module="orders.web.api", path="orders/web/api.py")
        (self.root / "orders/api.py").unlink()
        self.components.append({"id": "orders.web", "module": "orders.web",
                                "path": "orders/web/__init__.py", "layer": "api"})
        self.write("orders/web/api.py", "from ..database import save_order\n")
        self.write("orders/web/__init__.py", "from .. import database\n")
        self.declare()
        self.assertEqual(len(self.check()["violations"]), 2)

    def test_rule_name_and_custom_layer_domain_are_configurable(self):
        self.components[0]["layer"] = "presentation"
        self.declare(layers=["presentation", "service", "database"])
        self.rule.write_text("context Dependency inv CustomBoundary: "
                             "self.kind = 'IMPORTS' implies self.target.layer <> 'service'")
        report = self.check()
        self.assertEqual(report["rule"]["id"], "CustomBoundary")
        self.assertEqual(len(report["violations"]), 1)
        self.assertEqual(report["violations"][0]["rule_id"], "CustomBoundary")

    def test_rule_replacement_changes_verdict(self):
        self.write("orders/api.py", "import orders.database\n")
        self.assertEqual(len(self.check()["violations"]), 1)
        self.rule.write_text("context Dependency inv DifferentRule: self.target.layer <> 'never'")
        self.assertEqual(self.check()["violations"], [])

    def test_boolean_composition_and_kind_navigation(self):
        self.rule.write_text("context Dependency inv BooleanBoundary: "
                             "not (self.source.layer = 'api' and self.target.layer = 'database') "
                             "or self.kind <> 'IMPORTS'")
        self.assertEqual(self.check()["status"], "pass-within-scope")
        self.write("orders/api.py", "import orders.database\n")
        self.assertEqual(len(self.check()["violations"]), 1)

    def test_unknown_import_new_file_and_violation_keep_partial_coverage(self):
        self.write("orders/api.py", "import orders.database\nimport unknown\n")
        self.write("orders/extra.py", "pass\n")
        report = self.check()
        self.assertEqual(report["status"], "violations")
        self.assertEqual(report["coverage"]["status"], "partial")
        self.assertEqual(report["coverage"]["unresolved_imports"][0]["module"], "unknown")
        self.assertEqual(report["coverage"]["unmodeled_python_files"], ["orders/extra.py"])
        self.assertIn("orders/extra.py", report["coverage"]["python_file_inventory"])

    def test_unknown_import_without_violation_is_incomplete(self):
        self.write("orders/api.py", "import unknown\n")
        self.assertEqual(self.check()["status"], "incomplete")

    def test_exclusions_require_reasons_and_cannot_hide_component(self):
        self.write("orders/api.py", "import json\n")
        self.declare(excluded_modules=[{"module": "json", "reason": "stdlib out of scope"}])
        report = self.check()
        self.assertEqual(report["status"], "pass-within-scope")
        self.assertEqual(len(report["coverage"]["excluded_imports"]), 1)
        self.declare(excluded_modules=[{"module": "orders", "reason": "hide violation"}])
        with self.assertRaisesRegex(ValueError, "hide"):
            self.check()
        self.declare(excluded_modules=[{"module": "json"}])
        with self.assertRaisesRegex(ValueError, "reason"):
            self.check()

    def test_invalid_input_never_passes(self):
        for alteration in ("unknown_layer", "duplicate_id", "escape", "mapping"):
            with self.subTest(alteration=alteration):
                original = dict(self.components[0])
                if alteration == "unknown_layer":
                    self.components[0]["layer"] = "apis"
                elif alteration == "duplicate_id":
                    self.components[0]["id"] = self.components[1]["id"]
                elif alteration == "escape":
                    self.components[0]["path"] = "../outside.py"
                else:
                    self.components[0]["path"] = "orders/wrong.py"
                self.declare()
                with self.assertRaises(ValueError):
                    self.check()
                self.components[0] = original
        self.declare()
        self.write("orders/api.py", "from broken syntax\n")
        with self.assertRaises(SyntaxError):
            self.check()

    def test_unsupported_or_malformed_rule_errors_even_without_edges(self):
        for item in self.components:
            self.write(item["path"], "pass\n")
        for expression in ("self.source.layer =", "Component.allInstances()->size() > 1", "true",
                           "self.target.missing = 'api'"):
            with self.subTest(expression=expression):
                self.rule.write_text("context Dependency inv Broken: " + expression)
                with self.assertRaises(Exception):
                    self.check()

    def test_cli_json_exit_codes_and_saved_error_replaces_old_pass(self):
        output = self.workspace / "reports/boundary.json"
        args = [sys.executable, str(SCRIPT), str(self.root), "--components", str(self.manifest),
                "--rule", str(self.rule), "--authority", "demo: fixture", "--output", str(output)]
        for statement, code, status in [("import orders.service", 0, "pass-within-scope"),
                                        ("import orders.database", 1, "violations"),
                                        ("import unknown", 2, "incomplete"),
                                        ("broken syntax", 2, "error")]:
            with self.subTest(status=status):
                self.write("orders/api.py", statement + "\n")
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                printed = json.loads(result.stdout)
                self.assertEqual(printed["status"], status)
                self.assertEqual(json.loads(output.read_text()), printed)

    def test_cli_malformed_ocl_returns_json_error_and_preserves_inputs(self):
        self.rule.write_text("context Dependency inv Broken: self.source.layer =")
        args = [sys.executable, str(SCRIPT), str(self.root), "--components", str(self.manifest),
                "--rule", str(self.rule), "--authority", "demo: fixture"]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "error")
        before = self.manifest.read_bytes()
        result = subprocess.run(args + ["--output", str(self.manifest)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
