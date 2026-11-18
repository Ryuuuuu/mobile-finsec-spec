import base64,unittest
from pc.timeline import correlate

class TimelineTests(unittest.TestCase):
    def fixture(self):
        events=[{'event':'intent','action_id':'a','action':{'locator':'dev.finsec.qa.network:id/send_native','post':{'text':'sent:1'}}},
                {'event':'dispatch','action_id':'a','timestamp':'2026-01-01T00:00:00+00:00'},
                {'event':'result','action_id':'a','timestamp':'2026-01-01T00:00:02+00:00','status':'succeeded'}]
        def packet(i,path):return {'packet_id':str(i),'sequence':i,'request':{'timestamp':'2026-01-01T00:00:01+00:00','raw_base64':base64.b64encode(('GET '+path+' HTTP/1.1\r\n').encode()).decode()}}
        return events,[packet(1,'/synthetic/qa-test-native-1'),packet(2,'/favicon.ico')]
    def test_fixture_token_and_background_request_remain_distinct(self):
        events,packets=self.fixture();report=correlate(events,packets,'qa-test')
        self.assertEqual([r['relation'] for r in report['steps'][0]['requests']],['explicit_fixture_token','time_interval_only'])
        self.assertEqual(report['unlinked_packet_ids'],['2']);self.assertEqual(report['attribution'],'not_os_verified')
    def test_time_overlap_without_explicit_fixture_never_claims_causality(self):
        events,packets=self.fixture();report=correlate(events,packets)
        self.assertTrue(all(r['relation']=='time_interval_only' for r in report['steps'][0]['requests']))
        self.assertEqual(report['unlinked_packet_ids'],['1','2'])
