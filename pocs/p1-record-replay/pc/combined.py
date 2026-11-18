"""Explicit start/stop barrier for P1 input and P2 recording; no atomicity claim."""
from .core import Journal,atomic
from uuid import uuid4

class NetworkStartRejected(RuntimeError):
    """The adapter confirms RECORD did not apply; do not stop another recording."""

class CombinedRun:
    def __init__(self,engine,network,output):
        self.engine=engine;self.network=network;self.output=output;self.state='idle';self.j=None;self.link={};self.terminated=False;self.stop_attempted=False
        self.input_start=engine.start;self.input_finish=engine.finish;self.input_replay=getattr(engine,"replay",None);self.preflight=lambda:None
        self.network_start_attempted=False
    def start_network(self):
        recording_id='p1-'+uuid4().hex
        self.link['network_recording_id']=recording_id
        self.save()  # Persist intended scope before dispatch, including uncertain acknowledgements.
        self.network_start_attempted=True
        try:
            result=self.network.command('RECORD',device_id='selected-device',app_id=self.engine.a.package,recording_id=recording_id)
            if result.get('recording_id')!=recording_id:raise RuntimeError('Network RECORD scope mismatch')
            return result
        except NetworkStartRejected:
            self.network_start_attempted=False
            raise
    def stop_network(self):
        return self.network.command('STOP',expected_recording_id=self.link['network_recording_id'])
    def save(self):
        atomic(self.j.path/'combined.json',dict(self.link,status=self.state))
        if self.engine.j and self.engine.j.id==self.link.get('input_recording_id'):atomic(self.engine.j.path/'combined-link.json',dict(self.link,status=self.state))
    def start(self):
        if self.state!='idle':raise RuntimeError('Combined run not idle')
        self.terminated=False;self.stop_attempted=False;self.network_start_attempted=False
        self.j=Journal(self.output,'combined');self.state='starting';self.link={'combined_id':self.j.id}
        self.j.write('start_requested');self.save()
        try:
            self.preflight()
            self.input_start();self.link['input_recording_id']=self.engine.j.id
            self.j.write('input_prepared',recording_id=self.engine.j.id)
            result=self.start_network()
            self.link['network_recording_id']=result['recording_id']
            self.j.write('network_start_ack',recording_id=result['recording_id'])
            if self.engine.cancel.is_set():raise InterruptedError('STOP requested during start barrier')
            self.state='active';self.j.write('input_enabled');self.save()
        except Exception:
            self.engine.stop_requested();self.engine.mode='incomplete';self.abort('Start barrier failed');raise
    def finish(self):
        if self.state!='active':raise RuntimeError('Combined recording not active')
        self.state='stopping';self.j.write('input_closed');self.save()
        try:
            self.stop_attempted=True
            result=self.stop_network();self.link['network_stop']=result
            self.j.write('network_stop_ack',coverage=result.get('network_coverage'))
            self.input_finish()
            complete=self.engine.record['status']=='completed' and result.get('network_coverage')=='complete_for_supported_scope'
            self.state='completed' if complete else 'partial';self.j.write('combined_finished',status=self.state);self.save();self.terminated=True
            self.state='idle' if complete else 'partial'
        except Exception:
            self.engine.stop_requested();self.engine.mode='incomplete';self.abort('Stop barrier failed');raise
    def replay(self,route):
        if self.state!='idle':raise RuntimeError('Combined run not idle')
        self.terminated=False;self.stop_attempted=False;self.network_start_attempted=False
        self.j=Journal(self.output,'combined');self.state='starting'
        self.link={'combined_id':self.j.id,'kind':'replay','source_recording_id':route['recording_id']}
        self.engine.cancel.clear();self.j.write('start_requested');self.save()
        try:
            self.preflight()
            result=self.start_network()
            self.link['network_recording_id']=result['recording_id']
            self.j.write('network_start_ack',recording_id=result['recording_id'])
            if self.engine.cancel.is_set():raise InterruptedError('STOP requested during start barrier')
            self.state='replaying';self.j.write('input_enabled');self.save()
            result=self.input_replay(route)
            self.link['input_recording_id']=result['run_id'];self.link['input_status']=result['status']
            self.state='stopping';self.j.write('input_closed');self.save();self.stop_attempted=True
            stopped=self.stop_network();self.link['network_stop']=stopped
            self.j.write('network_stop_ack',coverage=stopped.get('network_coverage'))
            complete=result['status']=='succeeded' and stopped.get('network_coverage')=='complete_for_supported_scope'
            self.state='completed' if complete else 'partial'
            self.j.write('combined_finished',status=self.state);self.save();self.terminated=True
            self.state='idle' if complete else 'partial'
            return dict(result,status='succeeded' if complete else 'incomplete',input_status=result['status'])
        except Exception:
            self.engine.stop_requested();self.engine.mode='incomplete';self.abort('Replay barrier failed');raise
    def abort(self,reason):
        if not self.j or self.terminated or self.state in ('idle','completed'):return
        self.state='partial';self.j.write('gap',reason=reason)
        try:
            if not self.network_start_attempted:
                self.link['network_not_started']=True;self.j.write('network_stop_skipped_not_started')
            else:
                if self.stop_attempted:raise TimeoutError('STOP outcome remains uncertain; no automatic retry')
                self.stop_attempted=True
                self.link['network_stop']=self.stop_network()
                self.j.write('network_abort_stop_ack')
        except Exception:
            self.link['network_stop_uncertain']=True;self.j.write('network_stop_uncertain')
        if self.link.get('kind')!='replay' and hasattr(self.engine,'record') and self.engine.j and self.engine.j.id==self.link.get('input_recording_id'):
            self.engine.record['status']='incomplete';atomic(self.engine.j.path/'route.json',self.engine.record)
        self.save();self.terminated=True
