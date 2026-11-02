"""Tests for the SCIP adapter (via fakes, no real indexer/bindings needed)
and the tree-sitter fallback (skipped automatically if the optional
dependency is not installed -- no network access either way)."""
import unittest

import scip_loader
import treesitter_fallback


# --- Minimal fakes that duck-type the subset of scip_pb2's message shape
# --- convert_index actually reads, so the conversion logic is testable
# --- without the real protobuf bindings or an installed indexer.

DEFINITION_ROLE = scip_loader.DEFINITION_ROLE


class FakeSymbolInfo:
    def __init__(self, symbol, kind):
        self.symbol = symbol
        self.kind = kind


class FakeOccurrence:
    def __init__(self, symbol, symbol_roles, range_, enclosing_range=None):
        self.symbol = symbol
        self.symbol_roles = symbol_roles
        self.range = range_
        self.enclosing_range = enclosing_range or []


class FakeDocument:
    def __init__(self, relative_path, symbols, occurrences):
        self.relative_path = relative_path
        self.symbols = symbols
        self.occurrences = occurrences


class FakeIndex:
    def __init__(self, documents):
        self.documents = documents


class TestScipLoader(unittest.TestCase):
    def test_import_error_is_actionable_when_bindings_missing(self):
        with self.assertRaises(ImportError) as ctx:
            scip_loader.load_scip_index("nonexistent.scip")
        self.assertIn("protoc", str(ctx.exception))

    # Source text whose coordinates line up with the fake occurrences below,
    # so _is_confirmed_call_site has real text to check against:
    #   line0: def helper():
    #   line1:     pass
    #   line2: (blank)
    #   line3: def caller():
    #   line4:           helper()      <- "helper" at cols 10-16, "(" at col 16
    _MOD_SOURCE = "def helper():\n    pass\n\ndef caller():\n          helper()\n"

    def test_converts_definitions_and_same_file_call(self):
        helper_def = FakeOccurrence("pkg/mod/helper().", DEFINITION_ROLE, [0, 0, 1, 0], enclosing_range=[0, 0, 1, 0])
        caller_def = FakeOccurrence("pkg/mod/caller().", DEFINITION_ROLE, [3, 0, 4, 0], enclosing_range=[3, 0, 4, 0])
        helper_ref = FakeOccurrence("pkg/mod/helper().", 0, [4, 10, 4, 16])
        doc = FakeDocument(
            "mod.py",
            [FakeSymbolInfo("pkg/mod/helper().", "Function"), FakeSymbolInfo("pkg/mod/caller().", "Function")],
            [helper_def, caller_def, helper_ref],
        )
        index = FakeIndex([doc])
        file_map = {"mod.py": {"id": "pkg.mod"}}

        functions, classes, contains, calls, unresolved = scip_loader.convert_index(
            index, file_map, source_by_path={"mod.py": self._MOD_SOURCE}
        )

        func_ids = {f["id"] for f in functions}
        self.assertEqual(len(func_ids), 2)
        self.assertTrue(all(f["claim_status"] if "claim_status" in f else True for f in functions))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["claim_status"], "observed")
        caller_id = next(f["id"] for f in functions if f["name"].startswith("caller"))
        callee_id = next(f["id"] for f in functions if f["name"].startswith("helper"))
        self.assertEqual(calls[0]["from"], caller_id)
        self.assertEqual(calls[0]["to"], callee_id)

    def test_reference_by_value_is_not_counted_as_a_call(self):
        # Regression: a real scip-typescript index emits an identical
        # Reference occurrence for `helper()` (a call) and `const x = helper;`
        # (passing the function by name, never invoked) -- confirmed by
        # running the real indexer against a fixture repo (see
        # FUNCTION_LEVEL.md). Without a source-text check, the second case
        # was wrongly turned into a CALLS edge.
        source = "def helper():\n    pass\n\ndef caller():\n    x = helper\n"
        #                                                    "helper" at cols 8-14, next char is "\n", not "("
        helper_def = FakeOccurrence("pkg/mod/helper().", DEFINITION_ROLE, [0, 0, 1, 0], enclosing_range=[0, 0, 1, 0])
        caller_def = FakeOccurrence("pkg/mod/caller().", DEFINITION_ROLE, [3, 0, 4, 0], enclosing_range=[3, 0, 4, 0])
        helper_ref = FakeOccurrence("pkg/mod/helper().", 0, [4, 8, 4, 14])
        doc = FakeDocument(
            "mod.py",
            [FakeSymbolInfo("pkg/mod/helper().", 0), FakeSymbolInfo("pkg/mod/caller().", 0)],
            [helper_def, caller_def, helper_ref],
        )
        index = FakeIndex([doc])
        file_map = {"mod.py": {"id": "pkg.mod"}}

        functions, classes, contains, calls, unresolved = scip_loader.convert_index(
            index, file_map, source_by_path={"mod.py": source}
        )
        self.assertEqual(calls, [])
        self.assertEqual(unresolved, [])

    def test_without_source_text_unconfirmable_reference_is_unresolved_not_a_call(self):
        helper_def = FakeOccurrence("pkg/mod/helper().", DEFINITION_ROLE, [0, 0, 1, 0], enclosing_range=[0, 0, 1, 0])
        caller_def = FakeOccurrence("pkg/mod/caller().", DEFINITION_ROLE, [3, 0, 4, 0], enclosing_range=[3, 0, 4, 0])
        helper_ref = FakeOccurrence("pkg/mod/helper().", 0, [4, 10, 4, 16])
        doc = FakeDocument(
            "mod.py",
            [FakeSymbolInfo("pkg/mod/helper().", 0), FakeSymbolInfo("pkg/mod/caller().", 0)],
            [helper_def, caller_def, helper_ref],
        )
        index = FakeIndex([doc])
        file_map = {"mod.py": {"id": "pkg.mod"}}

        functions, classes, contains, calls, unresolved = scip_loader.convert_index(index, file_map)
        self.assertEqual(calls, [])  # never fabricated without confirmation
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["reason"], "call_site_unconfirmed_no_source")

    def test_documents_outside_declared_components_are_skipped(self):
        doc = FakeDocument("not_declared.py", [], [])
        index = FakeIndex([doc])
        functions, classes, contains, calls, unresolved = scip_loader.convert_index(index, {})
        self.assertEqual(functions, [])
        self.assertEqual(calls, [])

    def test_classifies_definitions_when_symbol_kind_is_unset(self):
        # Regression: a real scip-typescript index (verified end-to-end,
        # see FUNCTION_LEVEL.md) leaves SymbolInformation.kind at 0
        # (Unspecified) for every symbol. The original implementation
        # classified on `kind` and so misclassified every real definition
        # as neither function nor class. kind=0 here reproduces that.
        func_def = FakeOccurrence("pkg/mod/helper().", DEFINITION_ROLE, [0, 0, 1, 0], enclosing_range=[0, 0, 1, 0])
        class_def = FakeOccurrence("pkg/mod/Widget#", DEFINITION_ROLE, [2, 0, 2, 10])
        doc = FakeDocument(
            "mod.py",
            [FakeSymbolInfo("pkg/mod/helper().", kind=0), FakeSymbolInfo("pkg/mod/Widget#", kind=0)],
            [func_def, class_def],
        )
        index = FakeIndex([doc])
        file_map = {"mod.py": {"id": "pkg.mod"}}
        functions, classes, contains, calls, unresolved = scip_loader.convert_index(index, file_map)
        self.assertEqual(len(functions), 1)
        self.assertEqual(len(classes), 1)
        self.assertEqual(functions[0]["name"], "helper")
        self.assertEqual(classes[0]["name"], "Widget")

    def test_parameter_symbol_is_not_misclassified_as_a_function(self):
        self.assertEqual(scip_loader._classify_symbol("pkg/mod/helper().(x)"), "other")
        self.assertEqual(scip_loader._classify_symbol("pkg/mod/helper()."), "function")

    def test_method_is_parented_to_its_class_not_the_file(self):
        class_def = FakeOccurrence("pkg/mod/Widget#", DEFINITION_ROLE, [0, 0, 5, 0], enclosing_range=[0, 0, 5, 0])
        method_def = FakeOccurrence("pkg/mod/Widget#render().", DEFINITION_ROLE, [1, 2, 3, 3], enclosing_range=[1, 2, 3, 3])
        doc = FakeDocument(
            "mod.py",
            [FakeSymbolInfo("pkg/mod/Widget#", 0), FakeSymbolInfo("pkg/mod/Widget#render().", 0)],
            [class_def, method_def],
        )
        index = FakeIndex([doc])
        file_map = {"mod.py": {"id": "pkg.mod"}}
        functions, classes, contains, calls, unresolved = scip_loader.convert_index(index, file_map)
        method = next(f for f in functions if f["name"] == "render")
        widget = next(c for c in classes if c["name"] == "Widget")
        self.assertEqual(method["parent"], widget["id"])
        self.assertIn((widget["id"], method["id"]), {(e["from"], e["to"]) for e in contains})

    def test_single_line_enclosing_range_containment_is_not_misread(self):
        # Regression: reading a 3-element range's index -2 as "end line"
        # actually reads its start_char, which would wrongly reject (or
        # wrongly accept) containment for a single-line function body.
        self.assertTrue(scip_loader._range_contains([3, 0, 40], [3, 10, 20]))
        self.assertFalse(scip_loader._range_contains([3, 0, 40], [4, 0, 5]))

    def test_reference_with_no_resolvable_target_is_unresolved_not_an_edge(self):
        # "    abcdef()" -- end_char=10 lands right before "(", confirming
        # this occurrence IS a call site; the point of this test is that an
        # external (unmodeled) callee still must not become a CALLS edge.
        source = "def caller():\n    abcdef()\n"
        caller_def = FakeOccurrence("pkg/mod/caller().", DEFINITION_ROLE, [0, 0, 2, 0], enclosing_range=[0, 0, 2, 0])
        external_ref = FakeOccurrence("stdlib/os/path/join().", 0, [1, 4, 1, 10])
        doc = FakeDocument(
            "mod.py",
            [FakeSymbolInfo("pkg/mod/caller().", "Function")],
            [caller_def, external_ref],
        )
        index = FakeIndex([doc])
        file_map = {"mod.py": {"id": "pkg.mod"}}
        functions, classes, contains, calls, unresolved = scip_loader.convert_index(
            index, file_map, source_by_path={"mod.py": source}
        )
        self.assertEqual(calls, [])
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["symbol"], "stdlib/os/path/join().")
        self.assertEqual(unresolved[0]["reason"], "unresolved_target")


@unittest.skipUnless(treesitter_fallback.is_available("javascript"), "tree_sitter_languages not installed")
class TestTreeSitterFallback(unittest.TestCase):
    def test_heuristic_calls_are_tagged_as_heuristic(self):
        source = b"function main() { helper(); }"
        calls = treesitter_fallback.extract_calls_heuristic(source, "javascript", "mod.js", "mod.js")
        self.assertTrue(len(calls) >= 1)
        self.assertTrue(all(c["claim_status"] == "observed-heuristic" for c in calls))
        self.assertIn("helper", [c["callee_name"] for c in calls])

    def test_ambiguous_name_match_is_not_resolved(self):
        calls = [{"from": "mod.js", "callee_name": "helper", "line": 1, "path": "mod.js"}]
        name_map = {"helper": ["pkg.a.helper", "pkg.b.helper"]}
        resolved = treesitter_fallback.resolve_heuristic_calls(calls, name_map)
        self.assertEqual(resolved, [])

    def test_unambiguous_name_match_resolves_as_heuristic(self):
        calls = [{"from": "mod.js", "callee_name": "helper", "line": 1, "path": "mod.js"}]
        name_map = {"helper": ["pkg.a.helper"]}
        resolved = treesitter_fallback.resolve_heuristic_calls(calls, name_map)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["claim_status"], "observed-heuristic")
        self.assertEqual(resolved[0]["to"], "pkg.a.helper")


class TestTreeSitterUnavailableIsExplicit(unittest.TestCase):
    def test_unknown_language_raises_clear_error(self):
        with self.assertRaises(treesitter_fallback.TreeSitterUnavailable):
            treesitter_fallback.extract_calls_heuristic(b"", "cobol", "mod.cob", "mod.cob")


if __name__ == "__main__":
    unittest.main()
