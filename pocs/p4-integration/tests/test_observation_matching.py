import unittest
from dataclasses import replace
from integration.observation_poc import Route,Applicability,Plan
from integration.observation_matching import TimingRule,QAEvent,match_timing

class TimingTests(unittest.TestCase):
    def setUp(self):
        self.routes=tuple(Route('route-A','v1',i,('tap','again')) for i in (0,1))
        self.rules=(TimingRule('before-check','state','QA_READY','before_dispatch'),
                    TimingRule('after-check','event','QA_SUBMIT','after_postcondition'))
        self.cells=tuple(Applicability(c.check_id,r.recording_id,r.occurrence,'applicable','QA_REQUIRED')
                         for c in self.rules for r in self.routes)
        self.events=tuple(QAEvent(phase,r.recording_id,r.version,r.content_hash,r.occurrence,'tap',phase,state,event)
            for r in self.routes for phase,state,event in [('before_dispatch','QA_READY','QA_ENTER'),('after_postcondition','QA_SENT','QA_SUBMIT')])

    def test_two_checks_resolve_distinct_phases_and_occurrences(self):
        result=match_timing(self.routes,self.cells,self.rules,self.events)
        self.assertEqual([r['status'] for r in result['rows']],['MATCHED']*4)
        self.assertEqual([r['occurrence'] for r in result['rows']],[0,1,0,1])
        self.assertEqual([r['phase'] for r in result['rows']],['before_dispatch']*2+['after_postcondition']*2)
        self.assertEqual(result,match_timing(self.routes,self.cells,self.rules,self.events))

    def test_repeated_screen_ambiguous_and_absent_unmatched_no_guess(self):
        events=(self.events[0],replace(self.events[0],event_id='repeat',step_id='again'),self.events[1])
        rows=match_timing(self.routes,self.cells,self.rules,events)['rows']
        self.assertEqual([r['status'] for r in rows],['AMBIGUOUS','UNMATCHED','MATCHED','UNMATCHED'])
        self.assertEqual(rows[0]['candidate_count'],2)
        self.assertIsNone(rows[0]['step_id']);self.assertIsNone(rows[1]['phase'])

    def test_reject_scope_duplicate_unsupported_and_bind_metadata_approval(self):
        for events in (self.events+(self.events[0],),(replace(self.events[0],route_version='v2'),),self.events*51):
            with self.assertRaises(ValueError):match_timing(self.routes,self.cells,self.rules,events)
        for rules in ((replace(self.rules[0],required_evidence=('raw_screen',)),self.rules[1]),
                      (replace(self.rules[0],condition_kind='command'),self.rules[1]),
                      (replace(self.rules[0],schema_version='v999'),self.rules[1])):
            with self.assertRaises(ValueError):match_timing(self.routes,self.cells,rules,self.events)
        a=match_timing(self.routes,self.cells,self.rules,self.events)
        b=match_timing(self.routes,self.cells,(replace(self.rules[0],condition_value='QA_OTHER'),self.rules[1]),self.events)
        p=Plan(self.routes,(),schema_version=2,selected_check_ids=tuple(r.check_id for r in self.rules),applicability=self.cells,observation_metadata_hash=a['metadata_hash'])
        with self.assertRaisesRegex(ValueError,'APPROVAL'):replace(p,observation_metadata_hash=b['metadata_hash']).validate(p.content_hash)
