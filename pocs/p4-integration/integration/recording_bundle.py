"""Publish a validated local recording bundle; trusted paths, worker thread only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
from .artifact_reader import bounded,decode,read_artifacts
from .recording_snapshot import export_recording


def publish_bundle(link_path,route_path,db_path,output_root):
    """Return paths only after staging/identity checks and same-volume publication.

    This detects source changes; it is not a transaction across P1 and P2 writers.
    The owning launcher supplies its registry paths, never remote request paths.
    """
    link_bytes=bounded(link_path,1024*1024);route_bytes=bounded(route_path,1024*1024)
    link=decode(link_bytes)
    if link.get('status') not in ('completed','partial') or link.get('kind')=='replay':
        raise ValueError('BUNDLE_NOT_TERMINAL')
    network_id=link.get('network_recording_id')
    root=Path(output_root)
    stage=Path(tempfile.mkdtemp(prefix='.bundle-',dir=root))
    final=root/('recording-'+uuid4().hex)
    try:
        (stage/'combined-link.json').write_bytes(link_bytes)
        (stage/'route.json').write_bytes(route_bytes)
        export_recording(db_path,stage/'packets.sqlite',network_id)
        if bounded(link_path,1024*1024)!=link_bytes or bounded(route_path,1024*1024)!=route_bytes:
            raise ValueError('BUNDLE_SOURCE_CHANGED')
        summary,_=read_artifacts(stage/'combined-link.json',stage/'route.json',stage/'packets.sqlite')
        if any(summary[key] not in ('complete','partial') for key in ('link_status','route_status','packet_status')):
            raise ValueError('BUNDLE_INVALID_ARTIFACTS')
        manifest=dict(contract='p1-p2-bundle.v1',recording_id=summary['recording_id'],
                      network_recording_id=network_id,
                      states={key:summary[key] for key in ('link_status','route_status','packet_status')},
                      files={name:hashlib.sha256((stage/name).read_bytes()).hexdigest()
                             for name in ('combined-link.json','route.json','packets.sqlite')})
        (stage/'manifest.json').write_text(json.dumps(manifest,sort_keys=True),encoding='utf-8')
        # Generated unique name, same parent/volume. Consumers enumerate only recording-*.
        os.rename(stage,final)
        return dict(link=final/'combined-link.json',route=final/'route.json',packets=final/'packets.sqlite')
    finally:
        if stage.exists():shutil.rmtree(stage)
