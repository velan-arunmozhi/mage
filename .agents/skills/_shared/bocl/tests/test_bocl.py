"""Exercise all six adapters through the actual pinned B-OCL interpreter."""

import copy
import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNTIME = Path(__file__).resolve().parents[1]
SKILLS = RUNTIME.parents[1]
spec = importlib.util.spec_from_file_location('mage_bocl', RUNTIME / 'validate_model.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
MUTATIONS = {
    'structural': ('target_layer', 'database'),
    'behavioral': ('to_state', 'done'),
    'ownership': ('presented_claim', 'grant.7'),
    'decision': ('verdict', 'prohibited'),
    'measurement': ('delta', -9.0),
    'provenance': ('cause', ''),
}


class BoclTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.model = self.directory / 'model.json'
        self.rule = self.directory / 'rule.ocl'

    def fixture(self, name):
        self.data = json.loads((SKILLS / name / 'assets/model.example.json').read_text())
        self.rule.write_text((SKILLS / name / 'assets/snapshot.example.ocl').read_text())
        self.save()

    def save(self):
        self.model.write_text(json.dumps(self.data))

    def check(self, rules=None):
        self.save()
        return checker.check(self.model, rules or [self.rule], 'demo: fixture')

    def cli(self, name, extra=()):
        return subprocess.run([sys.executable, str(SKILLS / name / 'scripts/validate_model.py'),
                               str(self.model), '--rule', str(self.rule), '--authority',
                               'demo: fixture', *extra], text=True, capture_output=True)

    def test_all_six_pass_and_detect_meaningful_violations(self):
        for name, (field, value) in MUTATIONS.items():
            with self.subTest(model=name):
                self.fixture(name)
                report = self.check()
                self.assertEqual(report['status'], 'pass-within-scope')
                self.assertEqual(report['engine_versions']['bocl'], '1.0.2')
                original_hash = report['input']['sha256']
                self.data['objects'][0]['attributes'][field] = value
                report = self.check()
                self.assertEqual(report['status'], 'violations')
                self.assertEqual(report['violations'][0]['id'], self.data['objects'][0]['id'])
                self.assertNotEqual(report['input']['sha256'], original_hash)
                self.assertEqual(report['violations'][0]['evidence'], self.data['objects'][0]['evidence'])
                result = self.cli(name)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)['model_class'], name)

    def test_behavioral_guard_and_transition_relation(self):
        self.fixture('behavioral')
        row = self.data['objects'][0]['attributes']
        for source, target, trigger, guard in itertools.product(
                ['pending', 'running', 'done'], ['pending', 'running', 'done'], ['start', 'complete'], [True, False]):
            row.update(from_state=source, to_state=target, trigger=trigger, guard_satisfied=guard)
            expected = guard and (source, target, trigger) in {
                ('pending', 'running', 'start'), ('running', 'done', 'complete')}
            self.assertIs(self.check()['results'][0]['satisfied'], expected)

    def test_ownership_same_holder_new_grant_expiry_and_rejected_actions(self):
        self.fixture('ownership')
        row = self.data['objects'][0]['attributes']
        for claim, actor, now, effect in itertools.product(
                ['grant.7', 'grant.8'], ['worker.A', 'worker.B'], [199, 200, 201], [True, False]):
            row.update(presented_claim=claim, actor=actor, observed_at=now, effect_applied=effect)
            expected = not effect or (claim == 'grant.8' and actor == 'worker.A' and now < 200)
            self.assertIs(self.check()['results'][0]['satisfied'], expected)

    def test_measurement_negative_margin_is_valid_evidence(self):
        self.fixture('measurement')
        self.data['objects'][0]['attributes'].update(observed=60.0, delta=10.0, margin=-10.0)
        self.assertEqual(self.check()['status'], 'pass-within-scope')
        self.data['objects'][0]['attributes']['reference_unit'] = 'seconds'
        self.assertEqual(self.check()['status'], 'violations')

    def test_new_invariant_changes_verdict_without_changing_runtime(self):
        self.fixture('structural')
        self.assertEqual(self.check()['status'], 'pass-within-scope')
        self.rule.write_text("context Dependency inv NoService: self.target_layer <> 'service'")
        self.assertEqual(self.check()['status'], 'violations')

    def test_unknown_and_empty_observations_do_not_pass(self):
        self.fixture('measurement')
        self.data['objects'][0]['attributes']['observed'] = None
        report = self.check()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['results'], [])
        self.assertEqual(report['coverage']['unknown_attributes'][0]['attribute'], 'observed')
        self.data['objects'] = []
        self.assertEqual(self.check()['status'], 'incomplete')
        self.rule.write_text('context Comparison inv Broken: self.observed =')
        with self.assertRaises(ValueError):
            self.check()

    def test_partial_coverage_can_coexist_with_violations(self):
        self.fixture('provenance')
        self.data['coverage']['status'] = 'partial'
        self.data['objects'][0]['attributes']['cause'] = ''
        report = self.check()
        self.assertEqual(report['status'], 'violations')
        self.assertEqual(report['coverage']['status'], 'partial')

    def test_type_errors_and_hostile_values_never_reach_evaluation(self):
        self.fixture('measurement')
        for value in [True, '40', float('nan'), float('inf'), '" or __import__("os")']:
            with self.subTest(value=value):
                self.data['objects'][0]['attributes']['observed'] = value
                with self.assertRaises(ValueError):
                    self.check()
        self.fixture('provenance')
        self.data['objects'][0]['attributes']['cause'] = '" or True or "'
        with self.assertRaises(ValueError):
            self.check()

    def test_malformed_rules_unsupported_domains_and_types_never_pass(self):
        self.fixture('measurement')
        expressions = ['self.observed', 'self.missing = 1', 'self.observed =',
                       'self.observed = true', 'self.unit < self.reference_unit',
                       'self.observed > 0 garbage', 'Comparison.allInstances()->size() > 0',
                       '__import__(\'os\')', 'self.observed / 2 = 20', 'true inv Other: true']
        for expression in expressions:
            with self.subTest(expression=expression):
                self.rule.write_text('context Comparison inv Bad: ' + expression)
                with self.assertRaises(ValueError):
                    self.check()

    def test_boolean_constants_numeric_precedence_unary_and_implication(self):
        self.fixture('measurement')
        self.rule.write_text('context Comparison inv Math: true and not false and '
                             '(self.observed + 2 * 5 = self.reference) and '
                             '(-self.delta = 10) and (false implies false implies true)')
        self.assertEqual(self.check()['status'], 'pass-within-scope')
        self.rule.write_text('context Comparison inv Math: self.observed > self.reference')
        self.assertEqual(self.check()['status'], 'violations')

    def test_multiple_rules_and_unchecked_classes(self):
        self.fixture('measurement')
        second = self.directory / 'second.ocl'
        second.write_text('context Comparison inv Budget: self.margin >= 0')
        self.assertEqual(len(self.check([self.rule, second])['results']), 2)
        with self.assertRaisesRegex(ValueError, 'Duplicate invariant'):
            self.check([self.rule, self.rule])
        self.data['schema']['Other'] = {'present': 'boolean'}
        self.data['objects'].append({'id': 'other.1', 'type': 'Other', 'attributes': {'present': True},
                                     'evidence': ['demo: fixture']})
        report = self.check()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['coverage']['unchecked_objects'], ['other.1'])

    def test_invalid_identity_schema_and_evidence(self):
        self.fixture('provenance')
        original = copy.deepcopy(self.data)
        for kind in ['duplicate', 'missing_attribute', 'bad_class', 'no_evidence']:
            with self.subTest(kind=kind):
                self.data = copy.deepcopy(original)
                if kind == 'duplicate':
                    self.data['objects'].append(copy.deepcopy(self.data['objects'][0]))
                elif kind == 'missing_attribute':
                    del self.data['objects'][0]['attributes']['cause']
                elif kind == 'bad_class':
                    self.data['objects'][0]['type'] = 'Missing'
                else:
                    self.data['objects'][0]['evidence'] = []
                with self.assertRaises(ValueError):
                    self.check()
        self.model.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            checker.load_json(self.model)

    def test_cli_exit_codes_error_replacement_and_model_isolation(self):
        self.fixture('provenance')
        output = self.directory / 'reports/check.json'
        for expected, code in [('pass-within-scope', 0), ('incomplete', 2), ('error', 2)]:
            if expected == 'incomplete':
                self.data['objects'][0]['attributes']['cause'] = None
                self.save()
            if expected == 'error':
                self.rule.write_text('context Operation inv Broken: self.cause =')
            result = self.cli('provenance', ['--output', str(output)])
            self.assertEqual(result.returncode, code, result.stderr)
            printed = json.loads(result.stdout)
            self.assertEqual(printed['status'], expected)
            self.assertEqual(printed, json.loads(output.read_text()))
        self.fixture('provenance')
        result = self.cli('behavioral')
        self.assertEqual(result.returncode, 2)
        self.assertIn('model_class behavioral', json.loads(result.stdout)['error'])

    def test_cli_preserves_inputs_and_aliases(self):
        self.fixture('provenance')
        alias = self.directory / 'alias.json'
        alias.symlink_to(self.model)
        hard = self.directory / 'hard.json'
        hard.hardlink_to(self.model)
        before = self.model.read_bytes()
        for output in [self.model, self.rule, alias, hard]:
            result = self.cli('provenance', ['--output', str(output)])
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['status'], 'error')
            self.assertEqual(self.model.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
