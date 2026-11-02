"""Tests for the shared node anchor contract and ID aliasing.

Asserts externally observable behavior: what an extractor puts on a node,
what the loader rejects, and whether an aliased relation still matches.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import function_extractor
import model_loader
import node_anchor
import policy_evaluator
import scip_loader

HERE = Path(__file__).resolve().parent


def _write_model(data):
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, handle)
    handle.close()
    return Path(handle.name)


def _base_model(**overrides):
    model = {
        "schema_version": 1,
        "components": [{"id": "a", "path": "a.py", "layer": "api"}],
        "external_systems": [],
        "relations": [],
        "policy": {
            "layers": ["api", "service", "database"],
            "relation_types": ["IMPORTS", "CALLS"],
            "matrix": {},
        },
        "constraints": [],
    }
    model.update(overrides)
    return model


class TestMakeAnchor(unittest.TestCase):
    def test_complete_anchor_is_labelled_complete(self):
        anchor = node_anchor.make_anchor(path="a.py", symbol="f", sha256="ab", lineno=3)
        self.assertEqual(anchor["status"], "complete")
        self.assertNotIn("missing", anchor)
        self.assertEqual(node_anchor.anchor_issues(anchor), [])

    def test_missing_hash_is_named_not_dropped(self):
        anchor = node_anchor.make_anchor(path="a.py", symbol="f", sha256=None)
        self.assertEqual(anchor["status"], "incomplete")
        self.assertEqual(anchor["missing"], ["sha256"])
        self.assertEqual(node_anchor.anchor_issues(anchor), [])

    def test_unknown_position_is_omitted_not_nulled(self):
        anchor = node_anchor.make_anchor(path="a.py", symbol="f", sha256="ab")
        for field in node_anchor.POSITION_FIELDS:
            self.assertNotIn(field, anchor)

    def test_anchor_claiming_false_completeness_is_an_issue(self):
        forged = {"path": "a.py", "symbol": "f", "sha256": None, "status": "complete"}
        self.assertTrue(node_anchor.anchor_issues(forged))

    def test_unknown_status_is_an_issue(self):
        self.assertTrue(node_anchor.anchor_issues(
            {"path": "a.py", "symbol": "f", "sha256": "ab", "status": "probably-fine"}))

    def test_end_before_start_is_an_issue(self):
        anchor = node_anchor.make_anchor(path="a.py", symbol="f", sha256="ab",
                                         lineno=9, end_lineno=2)
        self.assertTrue(node_anchor.anchor_issues(anchor))


class TestPythonExtractorAnchors(unittest.TestCase):
    def setUp(self):
        self.model = model_loader.load_model(HERE / "model_functions.json")
        self.result = function_extractor.extract_structure(
            HERE / "fixtures" / "functions_extra", self.model)

    def test_every_function_and_class_carries_a_complete_anchor(self):
        nodes = self.result["functions"] + self.result["classes"]
        self.assertTrue(nodes)
        for node in nodes:
            self.assertIn("anchor", node, node["id"])
            self.assertTrue(node_anchor.is_complete(node["anchor"]), node["id"])
            self.assertEqual(node_anchor.anchor_issues(node["anchor"]), [])

    def test_anchor_carries_the_file_source_hash(self):
        for node in self.result["functions"]:
            source = (HERE / "fixtures" / "functions_extra" / node["path"]).read_bytes()
            import hashlib
            self.assertEqual(node["anchor"]["sha256"], hashlib.sha256(source).hexdigest())

    def test_method_symbol_is_qualified_by_its_class(self):
        by_id = {c["id"]: c for c in self.result["functions"]}
        process = by_id["extra.worker.Worker.process"]
        self.assertEqual(process["anchor"]["symbol"], "Worker.process")

    def test_anchor_bounds_the_body(self):
        for node in self.result["functions"]:
            anchor = node["anchor"]
            self.assertIn("end_lineno", anchor)
            self.assertGreaterEqual(anchor["end_lineno"], anchor["lineno"])

    def test_legacy_five_tuple_still_unpacks(self):
        functions, classes, contains, calls, unresolved = function_extractor.extract_functions(
            HERE / "fixtures" / "functions_extra", self.model)
        self.assertEqual(functions, self.result["functions"])
        self.assertEqual(classes, self.result["classes"])
        self.assertEqual(contains, self.result["contains_edges"])
        self.assertEqual(calls, self.result["calls_edges"])
        self.assertEqual(unresolved, self.result["unresolved_calls"])


class TestDuplicateIds(unittest.TestCase):
    def test_colliding_definition_is_reported_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A property and its setter generate the same "<file>.value" ID.
            (root / "dup.py").write_text(
                "class Box:\n"
                "    @property\n"
                "    def value(self):\n"
                "        return 1\n"
                "    @value.setter\n"
                "    def value(self, v):\n"
                "        self._v = v\n"
            )
            model = _base_model(components=[
                {"id": "dup", "path": "dup.py", "layer": "service"}])
            result = function_extractor.extract_structure(root, model)
            ids = [d["id"] for d in result["duplicate_ids"]]
            self.assertIn("dup.Box.value", ids)
            # The first definition survives with its own evidence.
            kept = [f for f in result["functions"] if f["id"] == "dup.Box.value"]
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["anchor"]["lineno"], 3)


class TestScipAnchors(unittest.TestCase):
    """Fake SCIP objects, matching the shape test_scip_and_treesitter.py uses."""

    class _Occ:
        def __init__(self, symbol, roles, range_):
            self.symbol = symbol
            self.symbol_roles = roles
            self.range = range_

    class _Doc:
        def __init__(self, path, occurrences):
            self.relative_path = path
            self.occurrences = occurrences

    class _Index:
        def __init__(self, documents):
            self.documents = documents

    def _index(self):
        occ = self._Occ("scip-typescript npm p 1.0 `svc`/run().", 1, [4, 2, 9, 3])
        return self._Index([self._Doc("svc.ts", [occ])])

    def _files(self):
        return {"svc.ts": {"id": "svc", "path": "svc.ts", "layer": "service"}}

    def test_anchor_is_complete_when_source_is_supplied(self):
        source = {"svc.ts": "\n" * 3 + "function run() {\n  return 1;\n}\n"}
        functions, _c, _e, _calls, _u = scip_loader.convert_index(
            self._index(), self._files(), source_by_path=source)
        self.assertEqual(len(functions), 1)
        anchor = functions[0]["anchor"]
        self.assertTrue(node_anchor.is_complete(anchor))
        self.assertEqual(node_anchor.anchor_issues(anchor), [])

    def test_scip_lines_are_converted_to_one_based(self):
        source = {"svc.ts": "\n" * 12}
        functions, _c, _e, _calls, _u = scip_loader.convert_index(
            self._index(), self._files(), source_by_path=source)
        anchor = functions[0]["anchor"]
        self.assertEqual(anchor["lineno"], 5)      # SCIP 0-based line 4
        self.assertEqual(anchor["end_lineno"], 10)  # SCIP 0-based line 9

    def test_missing_source_yields_an_incomplete_anchor_naming_the_hash(self):
        functions, _c, _e, _calls, _u = scip_loader.convert_index(
            self._index(), self._files())
        anchor = functions[0]["anchor"]
        self.assertFalse(node_anchor.is_complete(anchor))
        self.assertEqual(anchor["missing"], ["sha256"])
        self.assertEqual(node_anchor.anchor_issues(anchor), [])


class TestLoaderAnchorValidation(unittest.TestCase):
    def _load(self, model):
        path = _write_model(model)
        try:
            return model_loader.load_model(path)
        finally:
            os.unlink(path)

    def test_file_components_still_need_no_anchor(self):
        self.assertTrue(self._load(_base_model()))

    def test_function_component_without_an_anchor_is_rejected(self):
        model = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api"},
            {"id": "a.f", "kind": "function", "parent": "a"},
        ])
        with self.assertRaises(model_loader.ModelValidationError):
            self._load(model)

    def test_function_component_with_a_malformed_anchor_is_rejected(self):
        model = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api"},
            {"id": "a.f", "kind": "function", "parent": "a",
             "anchor": {"path": "a.py", "symbol": "f", "sha256": None, "status": "complete"}},
        ])
        with self.assertRaises(model_loader.ModelValidationError):
            self._load(model)

    def test_declared_incomplete_anchor_loads(self):
        # An honestly-labelled gap is a coverage fact, not a malformed model.
        model = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api"},
            {"id": "a.f", "kind": "function", "parent": "a",
             "anchor": node_anchor.make_anchor(path="a.py", symbol="f")},
        ])
        self.assertTrue(self._load(model))


class TestAliases(unittest.TestCase):
    def _load(self, model):
        path = _write_model(model)
        try:
            return model_loader.load_model(path)
        finally:
            os.unlink(path)

    def test_relation_resolves_through_an_alias(self):
        model = _base_model(
            components=[
                {"id": "a", "path": "a.py", "layer": "api"},
                {"id": "b", "path": "b.py", "layer": "service", "aliases": ["b_old"]},
            ],
            relations=[{"from": "a", "to": "b_old", "type": "IMPORTS", "status": "sanctioned"}],
        )
        self.assertTrue(self._load(model))

    def test_alias_colliding_with_a_live_id_is_rejected(self):
        model = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api"},
            {"id": "b", "path": "b.py", "layer": "service", "aliases": ["a"]},
        ])
        with self.assertRaises(model_loader.ModelValidationError):
            self._load(model)

    def test_ambiguous_alias_is_rejected(self):
        model = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api", "aliases": ["shared"]},
            {"id": "b", "path": "b.py", "layer": "service", "aliases": ["shared"]},
        ])
        with self.assertRaises(model_loader.ModelValidationError):
            self._load(model)

    def test_unresolvable_relation_endpoint_is_still_rejected(self):
        model = _base_model(
            components=[{"id": "a", "path": "a.py", "layer": "api"}],
            relations=[{"from": "a", "to": "nope", "type": "IMPORTS", "status": "sanctioned"}],
        )
        with self.assertRaises(model_loader.ModelValidationError):
            self._load(model)

    def test_sanctioned_relation_survives_a_rename(self):
        model = _base_model(
            components=[
                {"id": "a", "path": "a.py", "layer": "api"},
                {"id": "b", "path": "b.py", "layer": "service", "aliases": ["b_old"]},
            ],
            relations=[{"from": "a", "to": "b_old", "type": "IMPORTS", "status": "sanctioned"}],
        )
        model["policy"]["matrix"] = {"IMPORTS": {"api": {"service": "permitted"}}}
        verdict, reason, _info = policy_evaluator.is_aligned(
            {"from": "a", "to": "b", "type": "IMPORTS"}, model)
        self.assertEqual(verdict, "permitted")
        self.assertEqual(reason, "permitted_and_sanctioned")

    def test_without_the_alias_the_same_edge_is_only_undeclared(self):
        model = _base_model(
            components=[
                {"id": "a", "path": "a.py", "layer": "api"},
                {"id": "b", "path": "b.py", "layer": "service"},
            ],
            relations=[{"from": "a", "to": "b_old", "type": "IMPORTS", "status": "sanctioned"}],
        )
        model["policy"]["matrix"] = {"IMPORTS": {"api": {"service": "permitted"}}}
        verdict, _reason, _info = policy_evaluator.is_aligned(
            {"from": "a", "to": "b", "type": "IMPORTS"}, model)
        self.assertEqual(verdict, "undeclared")

    def test_alias_order_does_not_change_the_model_hash(self):
        one = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api", "aliases": ["x", "y"]}])
        two = _base_model(components=[
            {"id": "a", "path": "a.py", "layer": "api", "aliases": ["y", "x"]}])
        self.assertEqual(model_loader.model_hash(one), model_loader.model_hash(two))


if __name__ == "__main__":
    unittest.main()
