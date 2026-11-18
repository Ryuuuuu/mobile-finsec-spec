"""Trusted local P2 v1 selected-record export; call off the UI/event-loop thread."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from .artifact_reader import decode


def _copy_packets(source,target,recording_id,check,max_bytes):
    total=0
    cursor=source.execute('SELECT id,sequence,length(CAST(data AS BLOB)),length(request),length(response) '
                          'FROM packets WHERE recording_id=? ORDER BY sequence LIMIT 101',(recording_id,))
    for count,(pid,seq,metadata,request,response) in enumerate(cursor,1):
        check()
        total+=(metadata or 0)+(request or 0)+(response or 0)
        if count>100 or metadata is None or metadata>65536 or total>max_bytes:
            raise ValueError('SNAPSHOT_LIMIT')
        row=source.execute('SELECT id,recording_id,sequence,data,request,response FROM packets '
                           'WHERE id=? AND recording_id=?',(pid,recording_id)).fetchone()
        target.execute('INSERT INTO packets VALUES (?,?,?,?,?,?)',row)


def export_recording(source_path,destination,recording_id,*,timeout=5,max_bytes=16*1024*1024):
    """Publish one terminal recording, preserve metadata verbatim, never overwrite.

    No untrusted request paths: the owning launcher must resolve its registry first.
    Limits align with the bounded P4 reader, not production-scale capture claims.
    """
    if not isinstance(recording_id,str) or not 0<len(recording_id)<=200:
        raise ValueError('INVALID_RECORDING')
    if type(timeout) not in (int,float) or not 0<timeout<=30:
        raise ValueError('INVALID_TIMEOUT')
    if type(max_bytes) is not int or not 1<=max_bytes<=16*1024*1024:
        raise ValueError('INVALID_LIMIT')
    source_path=Path(source_path);destination=Path(destination)
    if source_path.is_symlink() or not source_path.is_file():raise ValueError('INVALID_SOURCE')
    if destination.exists() or destination.is_symlink():raise FileExistsError('SNAPSHOT_EXISTS')
    deadline=time.monotonic()+timeout
    def check():
        if time.monotonic()>=deadline:raise TimeoutError('SNAPSHOT_TIMEOUT')
    fd,name=tempfile.mkstemp(prefix='.snapshot-',suffix='.sqlite',dir=destination.parent)
    os.close(fd);temporary=Path(name)
    try:
        with closing(sqlite3.connect(source_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=min(timeout,.2))) as source:
            source.execute('PRAGMA query_only=ON');source.execute('PRAGMA trusted_schema=OFF')
            source.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
            source.execute('BEGIN')
            if source.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('UNSUPPORTED_VERSION')
            row=source.execute('SELECT data FROM recordings WHERE id=? AND length(CAST(data AS BLOB))<=65536',(recording_id,)).fetchone()
            if row is None:raise ValueError('RECORDING_UNAVAILABLE')
            record=decode(row[0])
            if record.get('recording_id')!=recording_id:raise ValueError('RECORDING_MISMATCH')
            if record.get('status') not in ('completed','interrupted','failed'):raise ValueError('RECORDING_NOT_TERMINAL')
            with closing(sqlite3.connect(temporary)) as target:
                target.execute('PRAGMA page_size=4096');target.execute('PRAGMA max_page_count=4096')
                target.executescript('''CREATE TABLE recordings(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE packets(id TEXT PRIMARY KEY,recording_id TEXT NOT NULL,sequence INTEGER NOT NULL,
                        data TEXT NOT NULL,request BLOB,response BLOB);
                    CREATE INDEX packet_recording ON packets(recording_id,sequence);
                    PRAGMA user_version=1;''')
                target.execute('INSERT INTO recordings VALUES (?,?)',(recording_id,row[0]))
                _copy_packets(source,target,recording_id,check,max_bytes)
                check();target.commit()
        check()
        size=temporary.stat().st_size
        if size>max_bytes:raise ValueError('SNAPSHOT_LIMIT')
        digest=hashlib.sha256(temporary.read_bytes()).hexdigest()
        check()
        # Same-directory hard link publishes a closed file atomically, refusing races/overwrite.
        # Unsupported filesystems fail closed; no copy fallback that exposes partial output.
        os.link(temporary,destination)
        return dict(contract='p2-recording-snapshot.v1',recording_id=recording_id,sha256=digest,
                    bytes=size,source_status=record['status'])
    finally:
        for path in (temporary,Path(name+'-journal'),Path(name+'-wal'),Path(name+'-shm')):
            path.unlink(missing_ok=True)
