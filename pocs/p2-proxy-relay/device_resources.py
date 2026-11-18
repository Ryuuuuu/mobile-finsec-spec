"""Owned explicit ADB reverse ports and shared device exclusion. No tcp:0."""
import pathlib,random,subprocess,sys

class ReverseUncertain(RuntimeError):pass

def device_lease(device):
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'p1-record-replay'))
    from pc.core import Lease
    return Lease(device)

class Reservation:
    """Keep the GUI reservation while input sessions connect/disconnect."""
    def __init__(self,device,lease_factory=device_lease):
        self.lease=lease_factory(device);self.held=False
    def acquire(self):
        if self.held:
            if self.lease.quarantine.exists():raise RuntimeError('Device recovery required')
            return
        self.lease.acquire();self.held=True
    def poison(self,reason):self.lease.poison(reason)
    def release(self,clean=False):
        pass # Input disconnect must not release a live fixture reservation.
    def finish(self,clean=False):self.end(clean)
    def end(self,clean=False):
        if self.held:self.lease.release(clean=clean);self.held=False

class OwnedReverse:
    def __init__(self,adb,device,host_port,runner=subprocess.run,candidates=None):
        if type(host_port)!=int or not 1024<=host_port<=65535:raise ValueError('Invalid host port')
        self.adb=adb;self.device=device;self.host_port=host_port;self.runner=runner;self.port=None;self.uncertain=False
        self.candidates=candidates if candidates is not None else random.SystemRandom().sample(range(40000,60000),20)
    def command(self,*args):
        return self.runner([self.adb,'-s',self.device,'reverse',*args],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=10)
    def mappings(self):
        result=self.command('--list')
        if result.returncode:raise ReverseUncertain('Cannot verify reverse mappings')
        rows=[]
        for line in result.stdout.splitlines():
            fields=line.split()
            if not fields:continue # ADB may append blank separator lines.
            if len(fields)!=3:raise ReverseUncertain('Unexpected reverse mapping response')
            rows.append((fields[1],fields[2]))
        return rows
    def allocate(self):
        if self.port is not None:raise RuntimeError('Reverse already allocated')
        try:
            for port in self.candidates:
                if type(port)!=int or not 1024<=port<=65535:raise ValueError('Invalid device port')
                result=self.command('--no-rebind','tcp:'+str(port),'tcp:'+str(self.host_port))
                if result.returncode:
                    error=(result.stderr or '').lower()
                    if 'cannot rebind' in error or 'address already in use' in error:continue
                    raise ReverseUncertain('Reverse allocation failed; do not retry device operations')
                self.port=port;self.verify();return str(port)
            raise RuntimeError('No free candidate reverse port')
        except (OSError,subprocess.TimeoutExpired,ReverseUncertain):
            self.uncertain=True;raise ReverseUncertain('Reverse allocation outcome requires recovery') from None
    def verify(self):
        if self.port is None or self.uncertain:raise ReverseUncertain('No verified owned reverse mapping')
        try:
            matches=[local for remote,local in self.mappings() if remote=='tcp:'+str(self.port)]
            if matches!=['tcp:'+str(self.host_port)]:raise ReverseUncertain('Owned reverse changed or disappeared')
        except (OSError,subprocess.TimeoutExpired,ReverseUncertain):
            self.uncertain=True;raise ReverseUncertain('Owned reverse verification failed') from None
    def close(self):
        if self.uncertain:raise ReverseUncertain('Reverse cleanup requires explicit recovery')
        if self.port is None:return
        try:
            rows=self.mappings();matches=[local for remote,local in rows if remote=='tcp:'+str(self.port)]
            if matches and matches!=['tcp:'+str(self.host_port)]:raise ReverseUncertain('Mapping ownership changed; not removed')
            if matches:
                result=self.command('--remove','tcp:'+str(self.port))
                if result.returncode:raise ReverseUncertain('Reverse removal failed')
                if any(remote=='tcp:'+str(self.port) for remote,_ in self.mappings()):raise ReverseUncertain('Reverse removal not confirmed')
            self.port=None
        except (OSError,subprocess.TimeoutExpired,ReverseUncertain):
            self.uncertain=True;raise ReverseUncertain('Reverse cleanup not confirmed') from None
