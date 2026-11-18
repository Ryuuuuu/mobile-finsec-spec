"""Content-neutral cooperative orchestration POC; no P3, tool or verdict imports."""
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import time
from uuid import uuid4
from .lease import LeaseStore, LeaseError
from .skill_structure import load_skills, provider_context
from .recording_context import resolve_recording
from .artifact_reader import read_artifacts
from .packet_access import PacketGrant


class MockExecutor:
    async def run(self, context, progress):
        progress()
        await asyncio.sleep(0)
        return {'execution_status': 'completed'}


class StructureSupervisor:
    def __init__(self, root, skills, executor=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.skills=Path(skills);self.executor=executor or MockExecutor()
        self.lease=LeaseStore(self.root/'lease.sqlite')
        self.epoch='synthetic-'+uuid4().hex
        self.survivors=set()

    async def run(self, items, platform=None, timeout=0.2, progress_timeout=0.1,
                  recording_id=None, recordings=None, artifact_files=None):
        if (not isinstance(items,list) or not 1<=len(items)<=10
                or not all(isinstance(x,str) for x in items) or len(set(items))!=len(items)
                or platform not in (None,'aos','ios')):raise ValueError('INVALID_PLAN')
        for value in (timeout,progress_timeout):
            if type(value) not in (int,float) or not math.isfinite(value) or not 0.01<=value<=60:
                raise ValueError('INVALID_TIMEOUT')
        artifact_data=None
        if artifact_files is not None:
            if recording_id is not None or recordings is not None or not isinstance(artifact_files,dict) or set(artifact_files)!={'link','route','packets'}:
                raise ValueError('INVALID_ARTIFACT_SELECTION')
            recording,artifact_data=read_artifacts(artifact_files['link'],artifact_files['route'],artifact_files['packets'])
        else:
            recording=resolve_recording(recording_id,{} if recordings is None else recordings)
        run_id='synthetic-'+uuid4().hex
        output=self.root/run_id;output.mkdir()
        rows=[dict(item_id=i,execution_status='not_run',reason='NOT_REACHED',recording_context=deepcopy(recording)) for i in items]
        events=[];token=None;active=None;current=None;safe=True;grant=None
        result=dict(contract='structure-run.v1',run_id=run_id,synthetic=True,
                    execution_status='not_run',items=rows,events=events,recovery_required=False)
        def emit(kind,**data):events.append(dict(seq=len(events)+1,type=kind,**data))
        try:
            try:token=self.lease.acquire(run_id,self.epoch)
            except LeaseError:
                result['reason']='DEVICE_BUSY_OR_RECOVERY';return result
            if token is None:
                result['reason']='DEVICE_BUSY_OR_RECOVERY';return result
            snapshots=[]
            for index,item in enumerate(items):
                try:snapshots.append(load_skills(self.skills,item,platform))
                except (OSError,ValueError,UnicodeError):
                    rows[index]['reason']='SKILL_LOAD_FAILED'
                    result['reason']='PREFLIGHT_FAILED';return result
            result['execution_status']='running'
            for index,item in enumerate(items):
                current=index
                token=self.lease.activate_attempt(token,'synthetic-'+uuid4().hex)
                self.lease.authorize(token,'mock.execute')
                rows[index].update(execution_status='running',reason='STARTED')
                emit('item_started',item_id=item,skill_roles=[s['role'] for s in snapshots[index]['skills']])
                started=time.monotonic();last_progress=started
                def progress():
                    nonlocal last_progress
                    last_progress=time.monotonic()
                context=provider_context(snapshots[index]);context['item_id']=item
                context['recording_context']=deepcopy(recording)
                if artifact_data is not None:
                    context['artifact_data']=deepcopy(artifact_data)
                    if recording.get('packet_status') in ('complete','partial') and 'packets' in recording.get('source_hashes',{}):
                        grant=PacketGrant(artifact_files['packets'],recording['recording_id'],artifact_data['network_recording_id'],
                                          recording['source_hashes']['packets'],lambda t=token:self.lease.authorize(t,'mock.execute'))
                        # Function closure preserves the same revocable grant across deepcopy.
                        context['read_packet']=lambda rid,pid,side,g=grant:g.read(rid,pid,side)
                active=asyncio.create_task(self.executor.run(deepcopy(context),progress))
                failure=None
                while not active.done():
                    await asyncio.wait({active},timeout=0.005)
                    now=time.monotonic()
                    if not active.done() and now-started>=timeout:failure='ITEM_TIMEOUT';break
                    if not active.done() and now-last_progress>=progress_timeout:failure='PROGRESS_TIMEOUT';break
                if failure:
                    rows[index].update(execution_status='timed_out',reason=failure)
                    result['execution_status']='timed_out';break
                try:reply=active.result()
                except asyncio.CancelledError:reply=None
                except Exception:
                    rows[index].update(execution_status='failed',reason='EXECUTOR_ERROR')
                    result['execution_status']='failed';break
                if reply!={'execution_status':'completed'}:
                    rows[index].update(execution_status='failed',reason='EXECUTOR_EXIT_OR_INVALID_RESULT')
                    result['execution_status']='failed';break
                if grant is not None:
                    grant.revoke();rows[index]['packet_access_statuses']=list(grant.audit);grant=None
                rows[index].update(execution_status='completed',reason='EXECUTED')
                emit('item_completed',item_id=item)
                self.lease.begin_cleanup(token)
                token=self.lease.finish_item(token,True,'completed')
                active=None;current=None
            else:result['execution_status']='completed'
        except asyncio.CancelledError:
            result['execution_status']='cancelled'
            if current is not None:rows[current].update(execution_status='cancelled',reason='RUN_CANCELLED')
        except Exception:
            result['execution_status']='failed';result['reason']='STRUCTURE_ERROR'
            if current is not None:rows[current].update(execution_status='failed',reason='STRUCTURE_ERROR')
        finally:
            if grant is not None:
                grant.revoke()
                if current is not None:rows[current]['packet_access_statuses']=list(grant.audit)
            if active is not None and not active.done():
                active.cancel()
                done,_=await asyncio.wait({active},timeout=0.05)
                safe=bool(done)
                if not safe:
                    self.survivors.add(active)
                    def settled(task):
                        self.survivors.discard(task)
                        if not task.cancelled():task.exception()
                    active.add_done_callback(settled)
            if active is not None and active.done() and not active.cancelled():
                active.exception()  # consume owned failure; never log its text
            if token is not None:
                self.lease.begin_cleanup(token)
                self.lease.release(token,safe,'completed' if safe else 'unknown')
            result['recovery_required']=not safe
            emit('run_finished',execution_status=result['execution_status'],recovery_required=not safe)
            # Private local structural record; no skill text, model text or verdict field.
            temp=output/'result.json.tmp'
            temp.write_text(json.dumps(result,indent=2),encoding='utf-8')
            temp.replace(output/'result.json')
        return result
