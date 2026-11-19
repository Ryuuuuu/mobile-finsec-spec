import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from integration.observation_poc import (Applicability, Checkpoint, Plan, Route, Scene,
    ObservationPOC, SyntheticDeviceSlot, digest)


def fixture():
    routes=tuple(Route('same-route','v1',i,('tap',)) for i in (0,1))
    cps=tuple(Checkpoint('state','check-one',r.recording_id,r.version,r.content_hash,
                         r.occurrence,'tap','after_postcondition','QA_SENT') for r in routes)
    cells=tuple(Applicability('check-one',r.recording_id,r.occurrence,'applicable','QA_REQUIRED') for r in routes)
    return Plan(routes,cps,schema_version=2,selected_check_ids=('check-one',),applicability=cells)


class ApplicabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.plan=fixture()

    def owner(self,plan):
        return ObservationPOC(self.root,plan,plan.content_hash,SyntheticDeviceSlot())

    async def test_omitted_checkpoint_and_missing_capture_are_distinct_one_of_two(self):
        for omitted in (True,False):
            with self.subTest(omitted=omitted):
                plan=replace(self.plan,checkpoints=self.plan.checkpoints[:1]) if omitted else self.plan
                owner=self.owner(plan)
                result=await owner.run({('same-route',0,'tap'):Scene(),
                                        ('same-route',1,'tap'):Scene(missing=not omitted)})
                self.assertEqual(result['contract'],'synthetic-observation.v2')
                self.assertEqual(result['checks']['check-one']['routes_expected'],2)
                self.assertEqual(result['checks']['check-one']['routes_with_evidence'],1)
                self.assertEqual(result['checks']['check-one']['verdict'],'inconclusive')
                gap=next(r for r in result['rows'] if r['checkpoint']['occurrence']==1)
                self.assertEqual(gap['reason'],'PLAN_CHECKPOINT_MISSING' if omitted else 'EVIDENCE_INSUFFICIENT')
                self.assertIsNone(gap['evidence_ref']);self.assertEqual(gap['review'],'NOT_REVIEWED')
                self.assertEqual(len([e for e in owner.events if e['event']=='synthetic_input']),2)
                self.assertEqual(len(owner.tasks),1);self.assertEqual(len(owner.snapshots),1)
                if omitted:
                    self.assertIsNone(gap['checkpoint']['step_id'])
                    self.assertEqual(len(owner.rows),1)  # Report gap never becomes an engine checkpoint.
                self.assertEqual(json.loads((owner.root/'result.json').read_text()),result)

    async def test_nonapplicable_unknown_visible_without_entering_applicable_denominator(self):
        cells=(replace(self.plan.applicability[0],status='not_applicable',reason='QA_NOT_APPLICABLE'),
               replace(self.plan.applicability[1],status='unknown',reason='QA_SCOPE_UNKNOWN'))
        owner=self.owner(replace(self.plan,applicability=cells,checkpoints=()))
        result=await owner.run({('same-route',i,'tap'):Scene() for i in (0,1)})
        check=result['checks']['check-one']
        self.assertEqual((check['routes_expected'],check['routes_with_evidence']), (0,0))
        self.assertEqual((check['routes_not_applicable'],check['routes_unknown']), (1,1))
        self.assertEqual(check['verdict'],'inconclusive')
        self.assertEqual([r['reason'] for r in result['rows']],['NOT_APPLICABLE','APPLICABILITY_UNKNOWN'])
        self.assertEqual([r['applicability_reason'] for r in result['rows']],['QA_NOT_APPLICABLE','QA_SCOPE_UNKNOWN'])
        self.assertEqual(owner.tasks,[]);self.assertEqual(owner.snapshots,{})

    async def test_check_without_any_checkpoint_remains_in_result(self):
        extra=tuple(replace(c,check_id='check-two') for c in self.plan.applicability)
        plan=replace(self.plan,selected_check_ids=('check-one','check-two'),
                     applicability=self.plan.applicability+extra)
        owner=self.owner(plan);result=await owner.run({('same-route',i,'tap'):Scene() for i in (0,1)})
        self.assertEqual(result['checks']['check-two']['routes_expected'],2)
        self.assertEqual(result['checks']['check-two']['routes_with_evidence'],0)
        self.assertEqual(len([r for r in result['rows'] if r['reason']=='PLAN_CHECKPOINT_MISSING']),2)
        self.assertEqual(len(owner.tasks),2)

    def test_incomplete_duplicate_contradictory_and_unbounded_matrices_rejected(self):
        c=self.plan.applicability[0]
        cases=[replace(self.plan,applicability=self.plan.applicability[:1]),
               replace(self.plan,applicability=self.plan.applicability+(c,)),
               replace(self.plan,selected_check_ids=('check-one','check-one')),
               replace(self.plan,applicability=(replace(c,status='unknown',reason='QA_SCOPE_UNKNOWN'),self.plan.applicability[1])),
               replace(self.plan,applicability=(replace(c,status='not_applicable',reason='QA_NOT_APPLICABLE'),self.plan.applicability[1])),
               replace(self.plan,applicability=(replace(c,status=[]),self.plan.applicability[1])),
               replace(self.plan,applicability=(replace(c,recording_id='unselected'),self.plan.applicability[1])),
               replace(self.plan,applicability=(replace(c,reason='arbitrary reason'),self.plan.applicability[1])),
               replace(self.plan,applicability=(replace(c,occurrence=True),self.plan.applicability[1])),
               replace(self.plan,checkpoints=(replace(self.plan.checkpoints[0],check_id='foreign'),)),
               replace(self.plan,applicability=self.plan.applicability*51),
               replace(self.plan,applicability=list(self.plan.applicability))]
        for plan in cases:
            with self.subTest(plan=plan),self.assertRaises(ValueError):self.owner(plan)
        self.assertEqual(list(self.root.iterdir()),[])  # Validation precedes any result storage.

    async def test_cancel_keeps_plan_gap_distinct_from_unreached_checkpoint(self):
        owner=self.owner(replace(self.plan,checkpoints=self.plan.checkpoints[:1]))
        owner.cancel.set();result=await owner.run({})
        self.assertEqual(result['replay_status'],'cancelled')
        self.assertEqual({r['reason'] for r in result['rows']},
                         {'STEP_NOT_REACHED_REPLAY_CANCELLED','PLAN_CHECKPOINT_MISSING'})
        self.assertEqual(result['checks']['check-one']['routes_expected'],2)

    async def test_v1_hash_contract_and_approval_compatibility(self):
        plan=Plan(self.plan.routes,self.plan.checkpoints)
        legacy=asdict(plan);legacy.pop('selected_check_ids');legacy.pop('applicability');legacy.pop('observation_metadata_hash')
        self.assertEqual(plan.content_hash,digest(legacy))
        result=await self.owner(plan).run({('same-route',i,'tap'):Scene() for i in (0,1)})
        self.assertEqual(result['contract'],'synthetic-observation.v1')
        self.assertNotIn('applicability',result)
        with self.assertRaisesRegex(ValueError,'V1_APPLICABILITY'):self.owner(replace(plan,applicability=self.plan.applicability))
        changed=replace(self.plan,applicability=(replace(self.plan.applicability[0],status='unknown',reason='QA_SCOPE_UNKNOWN'),self.plan.applicability[1]),checkpoints=self.plan.checkpoints[1:])
        with self.assertRaisesRegex(ValueError,'APPROVAL'):
            changed.validate(self.plan.content_hash)
