"""Bounded offline reader for P1 route v1/v2, combined link, P2 SQLite v1."""
from copy import deepcopy
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3


def decode(data):
    def unique(pairs):
        value={}
        for k,v in pairs:
            if k in value:raise ValueError('DUPLICATE_KEY')
            value[k]=v
        return value
    return json.loads(data,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('NONFINITE')))


def bounded(path,limit):
    path=Path(path)
    if path.is_symlink():raise ValueError('SYMLINK')
    with path.open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('LIMIT')
    return data


def read_artifacts(link_path,route_path,db_path):
    summary=dict(contract='p1-p2-artifacts.v1',mode='recording_unavailable',
                 link_status='missing',route_status='not_read',packet_status='not_read',
                 source_hashes={},route_count=0,packet_count=0)
    payload={'actions':[],'packets':[]}
    try:
        data=bounded(link_path,1024*1024);link=decode(data)
        if ('schema_version' in link or link.get('kind')=='replay'):
            summary['link_status']='unsupported_version';return summary,payload
        if not all(isinstance(link.get(k),str) and 0<len(link[k])<=200 for k in ('combined_id','input_recording_id','network_recording_id')):
            raise ValueError('LINK')
        if link.get('status') not in ('completed','partial','active','starting','stopping','failed','incomplete'):
            raise ValueError('STATUS')
        summary.update(recording_id='synthetic-'+hashlib.sha256(link['combined_id'].encode()).hexdigest(),
                       link_status='complete' if link['status']=='completed' else 'partial')
        summary['source_hashes']['link']=hashlib.sha256(data).hexdigest()
    except FileNotFoundError:return summary,payload
    except (OSError,ValueError,TypeError,AttributeError,RecursionError):
        summary['link_status']='corrupt';return summary,payload
    try:
        data=bounded(route_path,1024*1024);route=decode(data)
        if type(route.get('schema_version')) is not int or route['schema_version'] not in (1,2):
            summary['route_status']='unsupported_version'
        else:
            if route.get('recording_id')!=link['input_recording_id']:raise ValueError('ID')
            if route.get('status') not in ('completed','incomplete'):raise ValueError('STATUS')
            # Reuse the actual P1 data DSL validator only; never import UI/device code.
            path=Path(__file__).resolve().parents[2]/'p1-record-replay/pc/protocol.py'
            spec=importlib.util.spec_from_file_location('p4_p1_data_protocol',path)
            protocol=importlib.util.module_from_spec(spec);spec.loader.exec_module(protocol)
            checked=deepcopy(route);checked['status']='completed'
            if route['status']=='incomplete' and route.get('actions')==[]:
                checked['actions']=[{'action_id':'synthetic-validation-only','action':{'type':'wait','timeout':1,'post':checked['initial']}}]
            protocol.route(checked)
            summary['route_status']='complete' if route['status']=='completed' else 'partial'
            summary['route_count']=len(route['actions'])
            summary['source_hashes']['route']=hashlib.sha256(data).hexdigest()
            payload['actions']=deepcopy(route['actions'])
    except FileNotFoundError:summary['route_status']='missing'
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):summary['route_status']='corrupt'
    summary['mode']='recorded_route' if summary['route_status']=='complete' else 'route_unavailable'
    try:
        db=Path(db_path)
        if not db.exists():raise FileNotFoundError()
        if db.is_symlink() or db.stat().st_size>16*1024*1024:raise ValueError('LIMIT')
        if any(Path(str(db)+suffix).exists() for suffix in ('-wal','-journal')):
            summary['packet_status']='unsealed';return summary,payload
        before=hashlib.sha256(bounded(db,16*1024*1024)).hexdigest()
        with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro&immutable=1',uri=True,timeout=.1)) as conn:
            conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
            calls=[0]
            def budget():
                calls[0]+=1
                return calls[0]>1000
            conn.set_progress_handler(budget,1000)
            if conn.execute('PRAGMA user_version').fetchone()[0]!=1:
                summary['packet_status']='unsupported_version';return summary,payload
            row=conn.execute('SELECT data FROM recordings WHERE id=? AND length(data)<=65536',(link['network_recording_id'],)).fetchone()
            if row is None:summary['packet_status']='missing';return summary,payload
            record=decode(row[0])
            if record.get('schema_version')!=1 or type(record.get('schema_version')) is not int:
                summary['packet_status']='unsupported_version';return summary,payload
            if record.get('recording_id')!=link['network_recording_id']:raise ValueError('ID')
            if summary['route_status'] in ('complete','partial') and record.get('attribution',{}).get('app_id')!=route['package_id']:raise ValueError('APP_SCOPE')
            if record.get('status') not in ('completed','interrupted','recording','stopping','failed'):raise ValueError('STATUS')
            count=conn.execute('SELECT count(*) FROM packets WHERE recording_id=?',(link['network_recording_id'],)).fetchone()[0]
            if count>100:raise ValueError('PACKET_LIMIT')
            packets=[]
            for pid,seq,data in conn.execute('SELECT id,sequence,data FROM packets WHERE recording_id=? ORDER BY sequence',(link['network_recording_id'],)):
                if len(data.encode())>65536:raise ValueError('PACKET_LIMIT')
                p=decode(data)
                if p.get('schema_version')!=1:raise ValueError('PACKET_VERSION')
                if p.get('recording_id')!=link['network_recording_id'] or p.get('packet_id')!=pid or p.get('sequence')!=seq or seq!=len(packets)+1:
                    raise ValueError('PACKET_ID_ORDER')
                if type(p.get('incomplete')) is not bool:raise ValueError('PACKET_STATE')
                packets.append({k:p.get(k) for k in ('packet_id','sequence','timestamp','kind','protocol','request','response','incomplete')})
            partial=(record['status']!='completed' or record.get('network_coverage')!='complete_for_supported_scope'
                     or record.get('persisted_packets')!=count or bool(record.get('gaps')) or any(p['incomplete'] for p in packets))
            summary.update(packet_status='partial' if partial else 'complete',packet_count=count)
            payload['packets']=packets
            payload['network_recording_id']=link['network_recording_id']
        after=hashlib.sha256(bounded(db,16*1024*1024)).hexdigest()
        if before!=after:raise ValueError('ARTIFACT_CHANGED')
        summary['source_hashes']['packets']=after
    except FileNotFoundError:summary['packet_status']='missing'
    except (OSError,ValueError,TypeError,KeyError,AttributeError,sqlite3.Error,RecursionError):
        summary['packet_status']='corrupt';summary['packet_count']=0;payload['packets']=[]
    summary['mode']='recorded_route' if summary['route_status']=='complete' else 'route_unavailable'
    return summary,payload

