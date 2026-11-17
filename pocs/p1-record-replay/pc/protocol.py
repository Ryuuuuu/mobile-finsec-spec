"""Strict versioned action DSL. Routes are data, never executable code."""
import json, math, re
PACKAGE = 'dev.finsec.poc'
PREFIX = PACKAGE + ':id/'
PUBLIC_TEXT = {'qa-user', 'qa-pass', 'DEMO-001', '1000'}
IDS = {'screen_state','username','password','login','transfer','recipient','amount','review','confirm','receipt','initial_state','secure_state'}

def keys(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        raise ValueError('Missing or unknown fields')

def package_name(value):
    if not isinstance(value,str) or len(value)>255 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',value):
        raise ValueError('Invalid Android package name')
    return value

def resource(value,package=PACKAGE):
    package_name(package)
    if package!=PACKAGE:
        if not isinstance(value,str) or not re.fullmatch(r'(?:'+re.escape(package)+r'|android):id/[A-Za-z0-9_.]+',value):
            raise ValueError('Resource id must belong to the selected app or android')
        return
    if not isinstance(value, str) or not value.startswith(PREFIX) or value[len(PREFIX):] not in IDS:
        raise ValueError('Unsupported resource id')

def condition(c,package=PACKAGE):
    keys(c, ['id'], ['text']); resource(c['id'],package)
    if 'text' in c and (not isinstance(c['text'], str) or len(c['text']) > 150): raise ValueError('Invalid condition text')

def geometry(g):
    keys(g,['width','height','rotation'])
    if any(type(g[k]) is not int or not 1 <= g[k] <= 10000 for k in ['width','height']): raise ValueError('Invalid geometry')
    if g['rotation'] not in ['PORTRAIT','LANDSCAPE']: raise ValueError('Invalid rotation')

def action(a,package=PACKAGE):
    keys(a,['type','timeout','post'],['locator','point','end','geometry','text'])
    if type(a['timeout']) not in (int,float) or not 1 <= a['timeout'] <= 15: raise ValueError('Finite timeout required')
    condition(a['post'],package)
    t=a['type']
    if t not in ['tap','swipe','text','back','wait']: raise ValueError('Unsupported action')
    allowed={'tap':{'locator','point','geometry'},'swipe':{'point','end','geometry'},'text':{'locator','text'},'back':set(),'wait':set()}[t]
    if set(a)-{'type','timeout','post'}-allowed: raise ValueError('Fields invalid for action')
    if 'locator' in a: resource(a['locator'],package)
    if t=='text':
        if not a.get('locator') or not isinstance(a.get('text'),str) or not 1<=len(a['text'])<=150: raise ValueError('Text and resource id required; maximum 150 characters')
        if package==PACKAGE and a['text'] not in PUBLIC_TEXT: raise ValueError('Only public fixture text allowed')
    if t=='tap' and not ('locator' in a or 'point' in a): raise ValueError('Tap target required')
    if t=='swipe' and not all(k in a for k in ['point','end','geometry']): raise ValueError('Swipe coordinates required')
    if ('point' in a) != ('geometry' in a): raise ValueError('Coordinate geometry required')
    if 'geometry' in a: geometry(a['geometry'])
    for k in ['point','end']:
        if k in a and (not isinstance(a[k],list) or len(a[k])!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v < 1 for v in a[k])): raise ValueError('Invalid normalized coordinate')

def route(r):
    keys(r,['schema_version','recording_id','status','device_id','package_id','target','initial','secure','network_coverage','actions'])
    if r['schema_version'] not in (1,2) or type(r['schema_version']) is not int or r['status']!='completed': raise ValueError('Only complete v1/v2 routes can replay')
    package=package_name(r['package_id'])
    fixture=r['schema_version']==1
    if (fixture and package!=PACKAGE) or (not fixture and package==PACKAGE) or r['network_coverage']!='none': raise ValueError('Unsupported target or coverage')
    if not isinstance(r['recording_id'],str) or not r['recording_id'] or not isinstance(r['device_id'],str) or not r['device_id']: raise ValueError('Identity required')
    if fixture:
        keys(r['target'],['version_code','version_name','apk_sha256'])
        if r['target']['version_code']!='1' or r['target']['version_name']!='1.0' or not re.fullmatch('[0-9a-f]{64}',r['target']['apk_sha256']): raise ValueError('Unsupported build')
        if r['initial'] != {'id':PREFIX+'initial_state','text':'reset:0::'}: raise ValueError('Expected explicit reset initial state')
        if r['secure'] not in ['secure:on','secure:off']: raise ValueError('Secure state required')
    else:
        keys(r['target'],['version_code','version_name','apk_sha256s'])
        if not isinstance(r['target']['version_code'],str) or not re.fullmatch(r'\d+',r['target']['version_code']) or not isinstance(r['target']['version_name'],str): raise ValueError('Invalid installed build')
        hashes=r['target']['apk_sha256s']
        if not isinstance(hashes,dict) or not hashes or len(hashes)>200: raise ValueError('APK manifest required')
        for name,digest in hashes.items():
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.apk',name) or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest): raise ValueError('Invalid APK manifest')
        condition(r['initial'],package)
        if r['secure']!='unknown': raise ValueError('General app secure state is unknown; no bypass or inference')
    if not isinstance(r['actions'],list) or not 1 <= len(r['actions']) <= 100: raise ValueError('1..100 steps required')
    seen=set()
    for s in r['actions']:
        keys(s,['action_id','action'])
        if not isinstance(s['action_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',s['action_id']) or s['action_id'] in seen: raise ValueError('Duplicate/invalid action id')
        seen.add(s['action_id']); action(s['action'],package)
    return r

def load(path):
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d: raise ValueError('Duplicate JSON key')
            d[k]=v
        return d
    with open(path,'rb') as f: data=f.read(1024*1024+1)
    if len(data)>1024*1024: raise ValueError('Route exceeds 1 MiB')
    return route(json.loads(data,object_pairs_hook=unique))

def view_point(x,y,view_w,view_h,image_w,image_h):
    scale=min(view_w/image_w,view_h/image_h)
    left=(view_w-image_w*scale)/2; top=(view_h-image_h*scale)/2
    point=[(x-left)/(image_w*scale),(y-top)/(image_h*scale)]
    if any(v<0 or v>=1 for v in point): raise ValueError('Outside image / letterbox')
    return point
