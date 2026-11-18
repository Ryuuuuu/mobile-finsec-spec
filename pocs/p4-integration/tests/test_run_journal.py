import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from integration.supervisor import StructureSupervisor
from integration.run_journal import list_runs,write_new

class JournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.runs=self.root/'runs';self.skills=self.root/'skills'
        for name in ('first','second','third'):
            p=self.skills/name/'common'/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('OPAQUE MOCK')
    async def test_live_before_final_and_fixed_mock_labels(self):
        entered=asyncio.Event();release=asyncio.Event()
        class Executor:
            async def run(_,context,progress):entered.set();await release.wait();return {'execution_status':'completed'}
        task=asyncio.create_task(StructureSupervisor(self.runs,self.skills,Executor()).run(['first'],timeout=1,progress_timeout=1,mock_outcomes={'first':'pass'}))
        await entered.wait()
        row,=list_runs(self.runs)
        self.assertEqual(row['storage_status'],'unfinalized');self.assertIsNone(row['execution_status'])
        live=(self.runs/row['run_id']/'live.jsonl').read_text()
        self.assertIn('item_started',live);self.assertNotIn('mock_assessment',live)
        self.assertFalse((self.runs/row['run_id']/'result.json').exists())
        release.set();result=await task
        self.assertEqual(result['items'][0]['mock_assessment']['label'],'양호')
        self.assertEqual(list_runs(self.runs)[0]['storage_status'],'finalized')
    async def test_multiple_dates_outcomes_and_order(self):
        s=StructureSupervisor(self.runs,self.skills)
        for date,value in (('2026-11-17T12:00:00+00:00','pass'),('2026-11-18T10:00:00+00:00','fail'),('2026-11-18T11:00:00+00:00','inconclusive')):
            with patch('integration.run_journal.utc',return_value=date):
                result=await s.run(['first'],mock_outcomes={'first':value})
                self.assertEqual(result['items'][0]['mock_assessment']['reason'],'FIXTURE_ONLY_'+value.upper())
        rows=list_runs(self.runs,date='2026-11-18')
        self.assertEqual(len(rows),2);self.assertGreater(rows[0]['started_at'],rows[1]['started_at'])
        self.assertEqual(len(list_runs(self.runs,limit=1)),1)
    async def test_cancel_and_partial_completion_are_finalized_not_success(self):
        entered=asyncio.Event()
        class Executor:
            async def run(_,context,progress):
                if context['item_id']=='first':return {'execution_status':'completed'}
                entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(StructureSupervisor(self.runs,self.skills,Executor()).run(['first','second','third'],mock_outcomes={'first':'fail','second':'pass'}))
        await entered.wait();task.cancel();result=await task
        self.assertEqual(result['completion'],{'completed':1,'selected':3})
        self.assertEqual([r['execution_status'] for r in result['items']],['completed','cancelled','not_run'])
        self.assertNotIn('mock_assessment',result['items'][1])
        row,=list_runs(self.runs);self.assertEqual((row['storage_status'],row['execution_status']),('finalized','cancelled'))
    async def test_marker_failure_leaves_unfinalized_and_hash_damage_corrupt(self):
        s=StructureSupervisor(self.runs,self.skills)
        def broken(path,value):
            if Path(path).name=='finalized.json':raise OSError('PRIVATE_ERROR')
            return write_new(path,value)
        with patch('integration.run_journal.write_new',side_effect=broken):
            with self.assertRaises(OSError):await s.run(['first'])
        self.assertEqual(list_runs(self.runs)[0]['storage_status'],'unfinalized')
        result=await s.run(['first']);path=self.runs/result['run_id']/'result.json';path.write_text('{}')
        row=next(r for r in list_runs(self.runs) if r['run_id']==result['run_id'])
        self.assertEqual(row['storage_status'],'corrupt')
    async def test_failed_run_not_fake_outcome(self):
        class Executor:
            async def run(_,context,progress):raise RuntimeError('PRIVATE_ERROR')
        result=await StructureSupervisor(self.runs,self.skills,Executor()).run(['first'],mock_outcomes={'first':'pass'})
        self.assertNotIn('mock_assessment',result['items'][0])
        self.assertEqual(list_runs(self.runs)[0]['execution_status'],'failed')
        self.assertNotIn('PRIVATE_ERROR',json.dumps(result))
