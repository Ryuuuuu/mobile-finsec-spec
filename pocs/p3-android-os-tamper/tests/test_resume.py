import copy
import json
from pathlib import Path
import unittest
from resume_gate import GATES, empty_plan, assess_readiness
from os_tamper.engine import assess


class ResumeTests(unittest.TestCase):
    def ready(self):
        p = empty_plan()
        p['gates'] = dict.fromkeys(GATES, True)
        p['transport'] = dict.fromkeys(('baseline', 'test'), 'device')
        p['cleanup'] = 'verified'
        return p

    def test_empty_is_blocked(self):
        r = assess_readiness(empty_plan())
        self.assertEqual(r['readiness'], 'blocked')
        self.assertEqual(r['device_execution'], 'not_run')

    def test_ready_is_not_execution_or_security_verdict(self):
        p = self.ready()
        for synthetic in (True, False):
            p['synthetic'] = synthetic
            r = assess_readiness(p)
            self.assertEqual(r['readiness'], 'ready_for_manual_review')
            self.assertEqual(r['verdict'], 'inconclusive')
            self.assertFalse(r['auto_resume'])

    def test_each_missing_gate_blocks(self):
        for key in GATES:
            p = self.ready(); p['gates'][key] = False
            self.assertEqual(assess_readiness(p)['blockers'], [key])

    def test_both_transports_and_recovery(self):
        for phase in ('baseline', 'test'):
            for state in ('not_checked', 'offline', 'unauthorized', 'disconnected', 'error'):
                p = self.ready(); p['transport'][phase] = state
                self.assertEqual(assess_readiness(p)['readiness'], 'blocked')
        for state in ('unknown', 'failed'):
            p = self.ready(); p['cleanup'] = state
            self.assertIn('recovery_review_required', assess_readiness(p)['blockers'])

    def test_strict_schema(self):
        p = self.ready(); p['gates'][GATES[0]] = 'yes'
        with self.assertRaises(ValueError): assess_readiness(p)
        p = self.ready(); p['private_device_serial'] = 'PRIVATE'
        with self.assertRaises(ValueError): assess_readiness(p)

    def test_no_mutation(self):
        p = self.ready(); original = copy.deepcopy(p)
        assess_readiness(p)
        self.assertEqual(p, original)


class ComparisonMatrixTests(unittest.TestCase):
    def result(self, edit=None):
        p = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/pass.json').read_text(encoding='utf-8'))
        if edit: edit(p)
        refs = {o['observation_id']: 'synthetic-evidence-' + str(i) for i, o in enumerate(p['observations'])}
        return assess(p, p['observations'], refs)[0]

    def test_complete_pair_can_model_block(self):
        self.assertEqual(self.result()['verdict'], 'pass')

    def test_complete_pair_can_model_unprotected_service(self):
        def edit(p): p['observations'][1].update(outcome='allowed', block_reason='none')
        self.assertEqual(self.result(edit)['verdict'], 'fail')

    def test_indicators_launch_crash_or_unrelated_block_not_proof(self):
        mutations = ({'state_proof': 'missing'}, {'outcome': 'launch_only'}, {'outcome': 'crash'},
                     {'oracle': 'missing'}, {'block_reason': 'unknown'}, {'state': 'unknown'})
        for changes in mutations:
            with self.subTest(changes=changes):
                r = self.result(lambda p: p['observations'][1].update(changes))
                self.assertEqual(r['verdict'], 'inconclusive')

    def test_missing_baseline_or_disconnected_before_test(self):
        for index in (0, 1):
            r = self.result(lambda p: p['observations'].pop(index))
            self.assertEqual(r['verdict'], 'inconclusive')

    def test_build_checkpoint_mismatch(self):
        for field in ('build_sha256', 'checkpoint_id', 'device_id'):
            r = self.result(lambda p: p['observations'][1].update({field: 'synthetic-mismatch'}))
            self.assertEqual(r['verdict'], 'inconclusive')

    def test_contradiction_not_resolved_by_majority(self):
        def edit(p):
            extra = copy.deepcopy(p['observations'][1]); extra.update(observation_id='synthetic-conflict', outcome='allowed', block_reason='none')
            p['observations'].append(extra)
        self.assertEqual(self.result(edit)['reason_code'], 'CONFLICTING_OBSERVATIONS')
