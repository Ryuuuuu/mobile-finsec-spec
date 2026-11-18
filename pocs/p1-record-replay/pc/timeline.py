"""Export local timestamp candidates and explicit disposable-fixture token links."""
import argparse,base64,datetime,json,pathlib,re,sys

def timestamp(value):return datetime.datetime.fromisoformat(value).timestamp()
def correlate(events,packets,prefix=None):
    steps=[];linked=set()
    for intent in (e for e in events if e['event']=='intent'):
        aid=intent['action_id'];dispatch=next((e for e in events if e['event']=='dispatch' and e['action_id']==aid),None)
        result=next((e for e in events if e['event']=='result' and e['action_id']==aid),None)
        item={'action_id':aid,'locator':intent['action'].get('locator'),'status':result.get('status') if result else 'unknown','requests':[]}
        if dispatch and result:
            start,end=timestamp(dispatch['timestamp']),timestamp(result['timestamp'])
            item.update(dispatch_utc=dispatch['timestamp'],result_utc=result['timestamp'])
            for packet in packets:
                request=packet.get('request')
                if not request:continue
                at=timestamp(request['timestamp'])
                if not start<=at<=end:continue
                match=False
                if prefix and re.fullmatch(r'qa-[a-z0-9-]{1,40}',prefix):
                    locator=intent['action'].get('locator','');post=intent['action'].get('post',{}).get('text','')
                    kind='native' if locator.endswith(':id/send_native') else 'webview' if locator.endswith(':id/send_webview') else None
                    if kind and re.fullmatch(r'sent:[0-9]+',post):
                        expected=('/synthetic/'+prefix+'-'+kind+'-'+post.split(':')[1]).encode()
                        line=base64.b64decode(request.get('raw_base64','')).split(b'\r\n')[0].split(b' ')
                        match=len(line)==3 and line[1]==expected
                item['requests'].append({'packet_id':packet['packet_id'],'sequence':packet['sequence'],'request_utc':request['timestamp'],'after_dispatch_ms':round((at-start)*1000,3),'relation':'explicit_fixture_token' if match else 'time_interval_only'})
                if match:linked.add(packet['packet_id'])
        steps.append(item)
    return {'schema_version':1,'attribution':'not_os_verified','clock':'same-PC UTC; wall-clock adjustments can affect intervals','steps':steps,'unlinked_packet_ids':[p['packet_id'] for p in packets if p['packet_id'] not in linked]}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input-dir',type=pathlib.Path,required=True);parser.add_argument('--network-db',type=pathlib.Path,required=True);parser.add_argument('--fixture-prefix');parser.add_argument('--out',type=pathlib.Path,required=True);args=parser.parse_args()
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'p2-proxy-relay'))
    from relay import query
    link=json.loads((args.input_dir/'combined-link.json').read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (args.input_dir/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    packets=[];offset=0
    while True:
        response=query(args.network_db,'packets',recording_id=link['network_recording_id'],limit=100,offset=offset)
        if not response['ok']:raise RuntimeError('Network query failed')
        rows=response['result']
        for row in rows:
            detail=query(args.network_db,'detail',packet_id=row['packet_id'])
            if not detail['ok']:raise RuntimeError('Packet detail unavailable')
            packets.append(detail['result'])
        if len(rows)<100:break
        offset+=len(rows)
    report=correlate(events,packets,args.fixture_prefix);report['combined_id']=link['combined_id'];report['combined_status']=link['status']
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'steps':len(report['steps']),'packets':len(packets),'unlinked':len(report['unlinked_packet_ids']),'combined_status':link['status']}))
if __name__=='__main__':main()
