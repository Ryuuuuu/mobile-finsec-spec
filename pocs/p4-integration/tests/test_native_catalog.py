import asyncio,importlib.util,json,tempfile,unittest
from pathlib import Path
from integration.mock_stdio import create_mock_api
from integration.ui_bridge import UIBridge
spec=importlib.util.spec_from_file_location('native_demo',Path(__file__).resolve().parents[1]/'scripts/prepare_native_demo.py');demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
class NativeCatalogTests(unittest.IsolatedAsyncioTestCase):
 async def test_named_timed_records_are_separate_and_invalid_metadata_blocks_selection(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);await demo.prepare(root);bridge=UIBridge('synthetic',create_mock_api(root));rows=bridge.recordings(1)['recordings']
   self.assertEqual([r['display_name'] for r in rows],['Synthetic route 1','Synthetic route 2']);self.assertTrue(all(r['selectable'] and r['recorded_at'] for r in rows));self.assertNotEqual(rows[0]['recording']['recording_id'],rows[1]['recording']['recording_id'])
   p=root/'recordings/demo-1/recording-meta.json';m=json.loads(p.read_text());m['recording_id']='synthetic-route-2';p.write_text(json.dumps(m));rows=bridge.recordings(2)['recordings'];self.assertFalse(rows[0]['selectable']);self.assertEqual(rows[0]['reason'],'RECORDING_METADATA_INVALID');self.assertTrue(rows[1]['selectable']);self.assertNotIn('demo-1',bridge.api.recordings)
   p.unlink();rows=bridge.recordings(3)['recordings'];self.assertEqual(rows[0]['display_name'],'demo-1');self.assertIsNone(rows[0]['recorded_at']);self.assertTrue(rows[0]['selectable'])
