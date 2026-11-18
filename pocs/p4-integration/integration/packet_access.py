"""Attempt-scoped, on-demand packet bytes for cooperative mock executors only."""
import base64
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from .artifact_reader import bounded,decode


class PacketGrant:
    def __init__(self,db,common_id,network_id,digest,authorize,limit=65536):
        if type(limit) is not int or not 1<=limit<=65536:raise ValueError('INVALID_LIMIT')
        self.db=Path(db);self.common_id=common_id;self.network_id=network_id
        self.digest=digest;self.authorize=authorize;self.limit=limit
        self.active=True;self.calls=0;self.bytes=0;self.audit=[]
    def revoke(self):self.active=False
    def read(self,recording_id,packet_id,direction):
        def finish(status,**extra):
            self.audit.append(status) if len(self.audit)<50 else None
            return dict(status=status,encoding='base64',complete=False,**extra)
        if not self.active:return dict(status='expired',complete=False)
        if recording_id!=self.common_id or direction not in ('request','response') or not isinstance(packet_id,str) or not 1<=len(packet_id)<=200:
            return finish('denied')
        try:self.authorize()
        except Exception:return finish('expired')
        self.calls+=1
        if self.calls>20 or self.bytes>=262144:return finish('limit')
        try:
            if any(Path(str(self.db)+s).exists() for s in ('-wal','-journal')):return finish('unsealed')
            before=hashlib.sha256(bounded(self.db,16*1024*1024)).hexdigest()
            if before!=self.digest:return finish('artifact_changed')
            with closing(sqlite3.connect(self.db.resolve().as_uri()+'?mode=ro&immutable=1',uri=True,timeout=.1)) as c:
                c.execute('PRAGMA query_only=ON');c.execute('PRAGMA trusted_schema=OFF')
                ticks=[0]
                def budget():ticks[0]+=1;return ticks[0]>1000
                c.set_progress_handler(budget,1000)
                if c.execute('PRAGMA user_version').fetchone()[0]!=1:return finish('unsupported_version')
                # direction is allowlisted; IDs are bound parameters, never SQL text.
                row=c.execute('SELECT data,length('+direction+'),substr('+direction+',1,1048577) FROM packets WHERE id=? AND recording_id=? AND length(data)<=65536',(packet_id,self.network_id)).fetchone()
            if row is None:return finish('missing')
            if row[1] is None:return finish('missing')
            if row[1]>1048576:return finish('limit')
            p=decode(row[0]);m=p.get(direction);raw=b'' if row[1]==0 else row[2]
            if p.get('schema_version')!=1 or p.get('packet_id')!=packet_id or p.get('recording_id')!=self.network_id or not isinstance(m,dict):return finish('corrupt')
            if (type(p.get('incomplete')) is not bool or type(m.get('stored_size')) is not int or m['stored_size']!=len(raw)
                    or type(m.get('size')) is not int or m['size']<len(raw) or type(m.get('truncated')) is not bool
                    or m['truncated']!=(m['size']>len(raw))
                    or m.get('stored_sha256')!=hashlib.sha256(raw).hexdigest()):return finish('corrupt')
            if not m['truncated'] and m.get('sha256')!=hashlib.sha256(raw).hexdigest():return finish('corrupt')
            if hashlib.sha256(bounded(self.db,16*1024*1024)).hexdigest()!=before:return finish('artifact_changed')
            take=min(len(raw),self.limit,262144-self.bytes);data=raw[:take];self.bytes+=take
            complete=not p['incomplete'] and not m['truncated'] and take==len(raw)
            status='complete' if complete else 'partial';self.audit.append(status) if len(self.audit)<50 else None
            return dict(status=status,complete=complete,encoding='base64',data=base64.b64encode(data).decode('ascii'),
                        delivered_size=take,stored_size=len(raw),original_size=m['size'],
                        delivery_truncated=take<len(raw),capture_truncated=m['truncated'],packet_incomplete=p['incomplete'],
                        stored_sha256=m['stored_sha256'])
        except (OSError,ValueError,TypeError,KeyError,AttributeError,sqlite3.Error,RecursionError):return finish('corrupt')
