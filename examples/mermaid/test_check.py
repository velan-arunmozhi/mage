"""Tests for mermaid structural model."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import model_loader, renderer, checker, policy_evaluator, extractor


class TestModelLoader(unittest.TestCase):
    def test_load_valid_model(self):
        model = model_loader.load_model(Path("model.json"))
        self.assertEqual(model["schema_version"], 1)

    def test_duplicate_id_rejected(self):
        bad = {
            "schema_version": 1,
            "components": [
                {"id": "a", "path": "a.py", "layer": "api"},
                {"id": "a", "path": "b.py", "layer": "service"},
            ],
            "external_systems": [],
            "relations": [],
            "policy": {
                "layers": ["api", "service", "database"],
                "relation_types": ["IMPORTS"],
                "matrix": {},
            },
            "constraints": [],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            fname = f.name
        try:
            with self.assertRaises(model_loader.ModelValidationError):
                model_loader.load_model(Path(fname))
        finally:
            os.unlink(fname)

    def test_unknown_layer_rejected(self):
        bad = {
            "schema_version": 1,
            "components": [{"id": "a", "path": "a.py", "layer": "bad"}],
            "external_systems": [],
            "relations": [],
            "policy": {
                "layers": ["api", "service", "database"],
                "relation_types": ["IMPORTS"],
                "matrix": {},
            },
            "constraints": [],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            fname = f.name
        try:
            with self.assertRaises(model_loader.ModelValidationError):
                model_loader.load_model(Path(fname))
        finally:
            os.unlink(fname)

    def test_unknown_relation_type_rejected(self):
        bad = {
            "schema_version": 1,
            "components": [{"id": "a", "path": "a.py", "layer": "api"}],
            "external_systems": [],
            "relations": [{"from": "a", "to": "a", "type": "BAD", "status": "sanctioned"}],
            "policy": {
                "layers": ["api", "service", "database"],
                "relation_types": ["IMPORTS"],
                "matrix": {},
            },
            "constraints": [],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            fname = f.name
        try:
            with self.assertRaises(model_loader.ModelValidationError):
                model_loader.load_model(Path(fname))
        finally:
            os.unlink(fname)


class TestRenderer(unittest.TestCase):
    def test_determinism(self):
        model = model_loader.load_model(Path("model.json"))
        r1 = renderer.render(model)
        r2 = renderer.render(model)
        self.assertEqual(r1, r2)

    def test_determinism_different_order(self):
        model = model_loader.load_model(Path("model.json"))
        model2 = json.loads(json.dumps(model))
        comps = list(model2["components"])
        comps.reverse()
        model2["components"] = comps
        r1 = renderer.render(model)
        r2 = renderer.render(model2)
        self.assertEqual(r1, r2)


class TestPolicy(unittest.TestCase):
    def test_policy_matrix_truth_table(self):
        model = model_loader.load_model(Path("model.json"))
        aligned = policy_evaluator.is_aligned(
            {"from": "orders.api", "to": "orders.service", "type": "IMPORTS"}, model
        )
        self.assertEqual(aligned[0], "permitted")
        aligned = policy_evaluator.is_aligned(
            {"from": "orders.service", "to": "orders.db", "type": "IMPORTS"}, model
        )
        self.assertEqual(aligned[0], "permitted")
        aligned = policy_evaluator.is_aligned(
            {"from": "orders.api", "to": "orders.db", "type": "IMPORTS"}, model
        )
        self.assertEqual(aligned[0], "forbidden")


class TestChecker(unittest.TestCase):
    def test_valid_fixture_exits_ok(self):
        model = model_loader.load_model(Path("model.json"))
        report = checker.check(Path("fixtures/valid"), model)
        self.assertEqual(report["status"], "pass-within-scope")

    def test_invalid_fixture_has_violation(self):
        model = model_loader.load_model(Path("model.json"))
        report = checker.check(Path("fixtures/invalid"), model)
        self.assertEqual(report["status"], "violations")
        self.assertEqual(len(report["violations"]), 1)

    def test_base_policy_binds(self):
        model = model_loader.load_model(Path("model_legalized.json"))
        base_model = model_loader.load_model(Path("model.json"))
        report = checker.check(Path("fixtures/invalid"), model, base_model=base_model)
        self.assertEqual(report["status"], "violations")

    def test_drift_detected(self):
        model = model_loader.load_model(Path("model.json"))
        diagram_path = Path("fixtures/valid/structural.mmd")
        diagram_path.write_text("stale")
        try:
            report = checker.check(Path("fixtures/valid"), model, diagram_path=diagram_path)
            self.assertEqual(report["status"], "model-stale")
        finally:
            if diagram_path.exists():
                diagram_path.unlink()


if __name__ == "__main__":
    unittest.main()
