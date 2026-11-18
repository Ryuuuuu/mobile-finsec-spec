"""Synthetic recording references only: no file loading, replay or packet parsing."""
from copy import deepcopy
import re


def identifier(value):
    return isinstance(value,str) and re.fullmatch(r'synthetic-[A-Za-z0-9_-]{1,80}',value) is not None


def resolve_recording(recording_id, catalog, app_id='dev.finsec.synthetic'):
    if app_id!='dev.finsec.synthetic':raise ValueError('MOCK_APP_REQUIRED')
    if not isinstance(catalog,dict) or len(catalog)>100:raise ValueError('INVALID_CATALOG')
    base=dict(contract='recording-context.v1',synthetic=True,app_id=app_id,
              recording_id=recording_id,selection='none',route=None,packets=None)
    if recording_id is None:
        base.update(mode='app_launch_default',actions=[{'operation':'app.launch','app_id':app_id}],
                    collection_status='not_selected')
        return base
    if not identifier(recording_id):raise ValueError('INVALID_RECORDING_ID')
    base['selection']='explicit'
    if recording_id not in catalog:
        base.update(mode='recording_unavailable',actions=[],collection_status='recording_missing')
        return base
    record=catalog[recording_id]
    if (not isinstance(record,dict) or set(record)!={'recording_id','app_id','route','packets'}
            or record['recording_id']!=recording_id or record['app_id']!=app_id):
        raise ValueError('RECORDING_SCOPE_MISMATCH')
    for kind in ('route','packets'):
        value=record[kind]
        if (not isinstance(value,dict) or set(value)!={'recording_id','ref_id','status','count'}
                or value['recording_id']!=recording_id
                or value['status'] not in ('complete','partial','missing','not_collected')):
            raise ValueError('INVALID_REFERENCE')
        if value['status'] in ('complete','partial'):
            if (not identifier(value['ref_id']) or type(value['count']) is not int
                    or not 0<=value['count']<=100000):raise ValueError('INVALID_REFERENCE')
        elif value['ref_id'] is not None or value['count'] is not None:
            raise ValueError('INVALID_ABSENCE')
        base[kind]=deepcopy(value)
    route=base['route'];packets=base['packets']
    base['actions']=[]
    base['mode']=('recorded_route' if route['count'] else 'recorded_route_empty') if route['status']=='complete' else 'route_unavailable'
    base['collection_status']='complete' if all(v['status']=='complete' for v in (route,packets)) else 'incomplete'
    return base
