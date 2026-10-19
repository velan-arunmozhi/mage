"""Tests for the Alloy structural pilot.

Mirrors examples/mermaid/test_check.py's suite shape so the two pilots are
assessable on the same terms. Split into two tiers:

- Pure tests (als generation, skolem parsing) use canned Alloy output through
  an injected ``run_command`` and need no Java or jar.
- Integration tests actually invoke the Alloy CLI and are skipped, not
  failed, when no jar is resolvable -- this mirrors the OCL pilot's own
  posture of making its external dependency a documented, not a silent,
  requirement.
"""
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

import als_writer
import alloy_runner
import checker
import model_loader

HERE = Path(__file__).resolve().parent


def fake_result(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class TestAlsWriter(unittest.TestCase):
    def setUp(self):
        self.model = model_loader.load_model(HERE / "model.json")

    def test_determinism(self):
        edges = [{"from": "orders.api", "to": "orders.service", "type": "IMPORTS"}]
        src1, map1 = als_writer.build_als(self.model, edges)
        src2, map2 = als_writer.build_als(self.model, edges)
        self.assertEqual(src1, src2)
        self.assertEqual(map1, map2)

    def test_determinism_different_component_order(self):
        edges = []
        model2 = json.loads(json.dumps(self.model))
        model2["components"] = list(reversed(model2["components"]))
        src1, _ = als_writer.build_als(self.model, edges)
        src2, _ = als_writer.build_als(model2, edges)
        self.assertEqual(src1, src2)

    def test_forbidden_cell_included_as_not_permitted(self):
        edges = []
        src, _ = als_writer.build_als(self.model, edges)
        # api -> database is "forbidden" in model.json and must not appear
        # as a permitted[] clause.
        self.assertNotIn("L_api = a and L_database = b", src)
        self.assertIn("L_api = a and L_service = b", src)

    def test_identifier_map_round_trips_edges(self):
        edges = [{"from": "orders.api", "to": "orders.db", "type": "IMPORTS"}]
        _, id_map = als_writer.build_als(self.model, edges)
        self.assertEqual(id_map["edges"]["E0"], edges[0])

    def test_unknown_layer_rejected_at_model_load(self):
        import os
        import tempfile
        bad = json.loads(json.dumps(self.model))
        bad["components"][0]["layer"] = "not-a-layer"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            fname = f.name
        try:
            with self.assertRaises(model_loader.ModelValidationError):
                model_loader.load_model(Path(fname))
        finally:
            os.unlink(fname)


class TestAlloyRunnerParsing(unittest.TestCase):
    """Pure parsing tests against canned Alloy CLI output -- no Java involved."""

    def test_no_counterexample_is_empty_stdout(self):
        def run_command(args):
            return fake_result(stdout="")
        hit, parsed = alloy_runner.run_check(Path("x.als"), "SomeCheck", Path("jar"), run_command=run_command)
        self.assertFalse(hit)
        self.assertIsNone(parsed)

    def test_counterexample_found_is_nonempty_instances(self):
        canned = json.dumps({
            "instances": [{
                "skolems": {"$NoForbiddenObserved_e": {"arity": 1, "data": [["E3$0"]]}},
            }],
        })
        def run_command(args):
            return fake_result(stdout=canned)
        hit, parsed = alloy_runner.run_check(Path("x.als"), "NoForbiddenObserved", Path("jar"), run_command=run_command)
        self.assertTrue(hit)
        atoms = alloy_runner.witness_atoms(parsed, "NoForbiddenObserved", "e")
        self.assertEqual(atoms, ["E3"])

    def test_nonzero_exit_raises(self):
        def run_command(args):
            return fake_result(stdout="", returncode=1, stderr="boom")
        with self.assertRaises(alloy_runner.AlloyError):
            alloy_runner.run_check(Path("x.als"), "SomeCheck", Path("jar"), run_command=run_command)

    def test_malformed_json_raises(self):
        def run_command(args):
            return fake_result(stdout="{not json")
        with self.assertRaises(alloy_runner.AlloyError):
            alloy_runner.run_check(Path("x.als"), "SomeCheck", Path("jar"), run_command=run_command)


class TestCheckerWithFakeAlloy(unittest.TestCase):
    """Exercises checker.check()'s report assembly against a fake Alloy
    backend, so the report shape is tested without Java."""

    def setUp(self):
        self.model = model_loader.load_model(HERE / "model.json")

    def test_valid_fixture_no_forbidden_edge(self):
        calls = []
        def run_command(args):
            calls.append(args)
            # --command is the arg right after "--command"
            name = args[args.index("--command") + 1]
            if name == "NoForbiddenObserved":
                return fake_result(stdout="")  # no counterexample: valid fixture has no forbidden edge
            return fake_result(stdout="")
        report = checker.check(HERE / "fixtures" / "valid", self.model, jar_path=str(HERE / "model.json"), run_command=run_command)
        self.assertEqual(report["violations"], [])
        self.assertFalse(report["alloy"]["checks"]["NoForbiddenObserved"]["counterexample_found"])
        self.assertEqual(len(calls), 2)  # both named checks invoked

    def test_invalid_fixture_reports_the_violating_edge(self):
        def run_command(args):
            name = args[args.index("--command") + 1]
            if name == "NoForbiddenObserved":
                canned = json.dumps({
                    "instances": [{"skolems": {"$NoForbiddenObserved_e": {"arity": 1, "data": [["E0$0"]]}}}],
                })
                return fake_result(stdout=canned)
            return fake_result(stdout="")
        report = checker.check(HERE / "fixtures" / "invalid", self.model, jar_path=str(HERE / "model.json"), run_command=run_command)
        self.assertEqual(report["status"], "violations")
        self.assertEqual(len(report["violations"]), 1)
        self.assertEqual(report["violations"][0]["from"], "orders.api")
        self.assertEqual(report["violations"][0]["to"], "orders.db")

    def test_transitive_path_sets_status_when_no_direct_violation(self):
        def run_command(args):
            name = args[args.index("--command") + 1]
            if name == "NoTransitiveApiToDatabase":
                return fake_result(stdout=json.dumps({"instances": [{"skolems": {}}]}))
            return fake_result(stdout="")
        report = checker.check(HERE / "fixtures" / "valid", self.model, jar_path=str(HERE / "model.json"), run_command=run_command)
        self.assertEqual(report["status"], "policy-transitive-path")

    def test_missing_jar_raises(self):
        import os
        saved = os.environ.pop(alloy_runner.ALLOY_JAR_ENV, None)
        try:
            with self.assertRaises(alloy_runner.AlloyError):
                checker.check(HERE / "fixtures" / "valid", self.model, jar_path="does-not-exist.jar")
        finally:
            if saved is not None:
                os.environ[alloy_runner.ALLOY_JAR_ENV] = saved


def _resolve_test_jar():
    return alloy_runner.find_jar(None)


@unittest.skipUnless(_resolve_test_jar(), "set ALLOY_JAR or place alloy.jar next to checker.py to run live Alloy integration tests")
class TestLiveAlloyIntegration(unittest.TestCase):
    """Actually shells out to java + the Alloy jar. Skipped, not failed, when
    no jar is resolvable, matching the pilot's documented external
    dependency rather than silently downgrading the suite."""

    def setUp(self):
        self.model = model_loader.load_model(HERE / "model.json")
        self.jar = _resolve_test_jar()

    def test_valid_fixture_exits_ok(self):
        report = checker.check(HERE / "fixtures" / "valid", self.model, jar_path=self.jar)
        self.assertEqual(report["violations"], [])
        self.assertFalse(report["alloy"]["checks"]["NoForbiddenObserved"]["counterexample_found"])

    def test_invalid_fixture_has_one_violation_at_right_evidence(self):
        report = checker.check(HERE / "fixtures" / "invalid", self.model, jar_path=self.jar)
        self.assertEqual(report["status"], "violations")
        self.assertEqual(len(report["violations"]), 1)
        violation = report["violations"][0]
        self.assertEqual(violation["evidence"]["line"], 1)
        self.assertEqual(violation["from"], "orders.api")
        self.assertEqual(violation["to"], "orders.db")

    def test_transitive_check_finds_the_layered_path(self):
        # model.json's own matrix permits api->service and service->database,
        # so the transitive-closure check is expected to find that path on
        # either fixture -- this is the pilot's headline differentiator, not
        # a bug. See README "What this pilot found that the others didn't".
        report = checker.check(HERE / "fixtures" / "valid", self.model, jar_path=self.jar)
        self.assertTrue(report["alloy"]["checks"]["NoTransitiveApiToDatabase"]["counterexample_found"])

    def test_cli_exit_codes(self):
        import os
        env = dict(**{"ALLOY_JAR": str(self.jar)})
        result = subprocess.run(
            ["python", str(HERE / "checker.py"), str(HERE / "fixtures" / "invalid")],
            capture_output=True, text=True, cwd=HERE,
            env={**os.environ, **env},
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "violations")

    def test_no_third_party_python_dependencies(self):
        # The Python side of this pilot (unlike the Alloy jar it shells out
        # to) uses nothing outside the standard library.
        import ast
        for module_name in ("als_writer", "alloy_runner", "checker", "model_loader", "extractor"):
            source = (HERE / f"{module_name}.py").read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module.split(".")[0]] if node.module else []
                else:
                    continue
                stdlib_and_local = {
                    "json", "os", "re", "sys", "hashlib", "subprocess", "tempfile",
                    "argparse", "pathlib", "typing", "ast",
                    "als_writer", "alloy_runner", "checker", "model_loader", "extractor",
                }
                for name in names:
                    self.assertIn(name, stdlib_and_local, f"{module_name}.py imports non-stdlib {name}")


if __name__ == "__main__":
    unittest.main()
