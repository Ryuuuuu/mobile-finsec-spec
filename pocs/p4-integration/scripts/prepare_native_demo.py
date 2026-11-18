"""Create two disposable synthetic P1/P2 records; never inspect or operate a device."""
import argparse,asyncio,base64,json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(BASE/'p2-proxy-relay'),str(BASE/'p1-record-replay')]
from relay import Store
from pc.core import atomic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integration.artifact_reader import read_artifacts
async def prepare(root):
    for number in (1,2):
        folder=root/'recordings'/('demo-'+str(number))
        if folder.exists():raise ValueError('Demo already exists; use a fresh disposable root')
        folder.mkdir(parents=True)
        rid='synthetic-route-'+str(number);net='synthetic-network-'+str(number)
        atomic(folder/'combined-link.json',dict(combined_id='synthetic-combined-'+str(number),input_recording_id=rid,network_recording_id=net,status='completed'))
        atomic(folder/'route.json',dict(schema_version=1,recording_id=rid,status='completed',device_id='synthetic-device',package_id='dev.finsec.poc',target=dict(version_code='1',version_name='1.0',apk_sha256='a'*64),initial={'id':'dev.finsec.poc:id/initial_state','text':'reset:0::'},secure='secure:off',network_coverage='none',actions=[dict(action_id='synthetic-action-'+str(number),action=dict(type='wait',timeout=1,post={'id':'dev.finsec.poc:id/screen_state','text':'SYNTHETIC_SCREEN'}))]))

        record=dict(schema_version=1,recording_id=net,session_id='synthetic-session',run_id=None,status='completed',network_coverage='complete_for_supported_scope',persisted_packets=1,gaps=[],attribution=dict(app_id='dev.finsec.poc',device_id='synthetic-device',confidence='unverified'))
        packet=dict(schema_version=1,packet_id='synthetic-packet-'+str(number),recording_id=net,sequence=1,timestamp='2026-11-18T00:00:00Z',kind='http',protocol='HTTP/1.1',incomplete=False,error=None,request=dict(raw_base64=base64.b64encode(f'GET /synthetic/{number} HTTP/1.1\r\n\r\n'.encode()).decode(),method='GET',target=f'/synthetic/{number}'),response=dict(raw_base64=base64.b64encode(b'HTTP/1.1 200 OK\r\n\r\n').decode(),status=200))
        store=Store(folder/'packets.sqlite');await store.start()
        try:await store.record(record);await store.packet(packet)
        finally:await store.close()
        canonical=read_artifacts(folder/'combined-link.json',folder/'route.json',folder/'packets.sqlite')[0]['recording_id']
        atomic(folder/'recording-meta.json',dict(schema_version=1,recording_id=canonical,display_name='Synthetic route '+str(number),recorded_at=f'2026-11-18T00:0{number}:00+00:00'))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);asyncio.run(prepare(p.parse_args().root))
