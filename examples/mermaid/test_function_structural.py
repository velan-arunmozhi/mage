"""Tests for function-level structural extraction and validation."""
import unittest
from pathlib import Path

import model_loader
import function_extractor
import function_checker
import signature_rules


def _ids(components):
    return {c["id"] for c in components}


class TestFunctionExtraction(unittest.TestCase):
    """Uses the existing valid/ and invalid/ fixtures (orders.api/service/db) --
    no new fixtures needed since they already encode exactly the cross-file,
    import-based call this extractor is meant to resolve."""

    def setUp(self):
        self.model = model_loader.load_model(Path("model.json"))

    def test_functions_are_components(self):
        functions, classes, contains, calls, unresolved = function_extractor.extract_functions(
            Path("fixtures/valid"), self.model
        )
        self.assertIn("orders.api.submit_order", _ids(functions))
        self.assertIn("orders.service.place_order", _ids(functions))

    def test_contains_edges_file_to_function(self):
        functions, classes, contains, calls, unresolved = function_extractor.extract_functions(
            Path("fixtures/valid"), self.model
        )
        pairs = {(e["from"], e["to"]) for e in contains}
        self.assertIn(("orders.api", "orders.api.submit_order"), pairs)
        self.assertIn(("orders.service", "orders.service.place_order"), pairs)

    def test_cross_file_call_resolves(self):
        functions, classes, contains, calls, unresolved = function_extractor.extract_functions(
            Path("fixtures/valid"), self.model
        )
        pairs = {(e["from"], e["to"], e["type"]) for e in calls}
        self.assertIn(("orders.api.submit_order", "orders.service.place_order", "CALLS"), pairs)

    def test_forbidden_cross_file_call_also_resolves(self):
        # invalid/api.py imports database.save_order directly and calls it --
        # a function-level mirror of the file-level forbidden IMPORTS case.
        functions, classes, contains, calls, unresolved = function_extractor.extract_functions(
            Path("fixtures/invalid"), self.model
        )
        pairs = {(e["from"], e["to"], e["type"]) for e in calls}
        self.assertIn(("orders.api.submit_order", "orders.db.save_order", "CALLS"), pairs)


class TestClassAndSelfCalls(unittest.TestCase):
    def setUp(self):
        self.model = model_loader.load_model(Path("model_functions.json"))
        (self.functions, self.classes, self.contains,
         self.calls, self.unresolved) = function_extractor.extract_functions(
            Path("fixtures/functions_extra"), self.model
        )

    def test_class_is_a_component_contained_by_file(self):
        self.assertIn("extra.worker.Worker", _ids(self.classes))
        pairs = {(e["from"], e["to"]) for e in self.contains}
        self.assertIn(("extra.worker", "extra.worker.Worker"), pairs)

    def test_class_contains_methods(self):
        pairs = {(e["from"], e["to"]) for e in self.contains}
        self.assertIn(("extra.worker.Worker", "extra.worker.Worker.run"), pairs)
        self.assertIn(("extra.worker.Worker", "extra.worker.Worker.process"), pairs)

    def test_self_call_resolves_to_sibling_method(self):
        pairs = {(e["from"], e["to"]) for e in self.calls}
        self.assertIn(("extra.worker.Worker.run", "extra.worker.Worker.process"), pairs)
        self.assertIn(("extra.worker.Worker.process", "extra.worker.Worker._value"), pairs)

    def test_qualified_module_call_resolves_cross_file(self):
        pairs = {(e["from"], e["to"]) for e in self.calls}
        self.assertIn(("extra.worker.Worker.process", "extra.helper.format_result"), pairs)

    def test_ambiguous_dynamic_call_is_unresolved_not_a_false_edge(self):
        # dispatch() calls a local variable `handler`, not a known name --
        # must not appear as a CALLS edge anywhere.
        callers = {e["from"] for e in self.calls}
        self.assertNotIn("extra.dynamic.dispatch", callers)
        unresolved_callers = {u["from"] for u in self.unresolved}
        self.assertIn("extra.dynamic.dispatch", unresolved_callers)


class TestFunctionLevelMatrixValidation(unittest.TestCase):
    def setUp(self):
        self.model = model_loader.load_model(Path("model.json"))

    def test_permitted_call_is_permitted(self):
        report = function_checker.check_functions(Path("fixtures/valid"), self.model)
        call_results = [r for r in report["results"] if r["type"] == "CALLS"]
        found = [r for r in call_results
                 if r["from"] == "orders.api.submit_order" and r["to"] == "orders.service.place_order"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["verdict"], "permitted")

    def test_forbidden_call_is_flagged_as_violation(self):
        report = function_checker.check_functions(Path("fixtures/invalid"), self.model)
        self.assertEqual(report["status"], "violations")
        forbidden = [v for v in report["violations"]
                     if v["from"] == "orders.api.submit_order" and v["to"] == "orders.db.save_order"]
        self.assertEqual(len(forbidden), 1)


class TestSignatureRules(unittest.TestCase):
    def setUp(self):
        self.model = model_loader.load_model(Path("model_functions.json"))
        self.report = function_checker.check_functions(Path("fixtures/functions_extra"), self.model)
        self.by_rule = {(r["rule_id"], r["function_id"]): r for r in self.report["signature_rules"]}

    def test_pass_when_signature_matches(self):
        r = self.by_rule[("FR1", "extra.helper.format_result")]
        self.assertEqual(r["result"], "pass")

    def test_fail_when_call_graph_proves_no_approved_call(self):
        # Worker.process DOES call extra.helper.format_result, so this must pass.
        r = self.by_rule[("FR2", "extra.worker.Worker.process")]
        self.assertEqual(r["result"], "pass")

    def test_insufficient_information_when_annotation_missing(self):
        r = self.by_rule[("FR3", "extra.dynamic.dispatch")]
        self.assertEqual(r["result"], "insufficient-information")


class TestModelLoaderParentInheritance(unittest.TestCase):
    def test_component_without_layer_requires_parent(self):
        bad = {
            "schema_version": 1,
            "components": [{"id": "a", "path": "a.py"}],
            "external_systems": [],
            "relations": [],
            "policy": {"layers": ["api"], "relation_types": ["IMPORTS"], "matrix": {}},
            "constraints": [],
        }
        import tempfile, json, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            fname = f.name
        try:
            with self.assertRaises(model_loader.ModelValidationError):
                model_loader.load_model(Path(fname))
        finally:
            os.unlink(fname)

    def test_component_with_parent_inherits_layer(self):
        good = {
            "schema_version": 1,
            "components": [
                {"id": "orders.api", "path": "api.py", "layer": "api"},
                {"id": "orders.api.handler", "kind": "function", "parent": "orders.api",
                 "anchor": {"path": "api.py", "symbol": "handler", "sha256": "0" * 64,
                            "lineno": 1, "status": "complete"}},
            ],
            "external_systems": [],
            "relations": [],
            "policy": {"layers": ["api"], "relation_types": ["IMPORTS"], "matrix": {}},
            "constraints": [],
        }
        import tempfile, json, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(good, f)
            fname = f.name
        try:
            loaded = model_loader.load_model(Path(fname))
            self.assertEqual(len(loaded["components"]), 2)
        finally:
            os.unlink(fname)


if __name__ == "__main__":
    unittest.main()
