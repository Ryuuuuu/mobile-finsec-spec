import asyncio,subprocess,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from device_resources import OwnedReverse,ReverseUncertain,Reservation
from tools.device_app_smoke import main

class FakeAdb:
    def __init__(self):self.maps={};self.calls=[]
    def __call__(self,argv,**kwargs):
        self.calls.append(argv[4:]);args=argv[4:];code=0;out='';error=''
        if args[0]=='--list':out=''.join('synthetic '+r+' '+h+'\n' for r,h in self.maps.items())
        elif args[0]=='--no-rebind':
            remote,host=args[1:]
            if remote in self.maps:code=1;error='cannot rebind existing socket'
            else:self.maps[remote]=host
        elif args[0]=='--remove':self.maps.pop(args[1],None)
        else:raise AssertionError(args)
        return SimpleNamespace(returncode=code,stdout=out,stderr=error)

class ReverseTests(unittest.TestCase):
    def test_two_owned_ports_survive_independent_cleanup(self):
        adb=FakeAdb();a=OwnedReverse('adb','synthetic',50001,adb,[41001]);b=OwnedReverse('adb','synthetic',50002,adb,[41001,41002])
        self.assertEqual(a.allocate(),'41001');self.assertEqual(b.allocate(),'41002')
        b.close();a.verify();self.assertEqual(adb.maps,{'tcp:41001':'tcp:50001'});a.close();self.assertEqual(adb.maps,{})
        self.assertFalse(any('tcp:0' in c or '--remove-all' in c for c in adb.calls))
    def test_changed_mapping_is_never_removed(self):
        adb=FakeAdb();a=OwnedReverse('adb','synthetic',50001,adb,[41001]);a.allocate();adb.maps['tcp:41001']='tcp:50002'
        with self.assertRaises(ReverseUncertain):a.close()
        self.assertFalse(any(c[0]=='--remove' for c in adb.calls));self.assertTrue(a.uncertain)
    def test_transport_restart_missing_mapping_blocks_use(self):
        adb=FakeAdb();a=OwnedReverse('adb','synthetic',50001,adb,[41001]);a.allocate();adb.maps.clear()
        with self.assertRaises(ReverseUncertain):a.verify()
        with self.assertRaises(ReverseUncertain):a.close()
    def test_allocation_timeout_is_not_retried_or_removed(self):
        runner=Mock(side_effect=subprocess.TimeoutExpired('adb',10));a=OwnedReverse('adb','synthetic',50001,runner,[41001,41002])
        with self.assertRaises(ReverseUncertain):a.allocate()
        with self.assertRaises(ReverseUncertain):a.close()
        self.assertEqual(runner.call_count,1)
    def test_absent_owned_mapping_cleanup_is_idempotent(self):
        adb=FakeAdb();a=OwnedReverse('adb','synthetic',50001,adb,[41001]);a.allocate();adb.maps.clear();a.close();a.close()
        self.assertFalse(any(c[0]=='--remove' for c in adb.calls))
    def test_unknown_error_not_retried(self):
        runner=Mock(return_value=SimpleNamespace(returncode=1,stdout='',stderr='unauthorized'))
        with self.assertRaises(ReverseUncertain):OwnedReverse('adb','synthetic',50001,runner,[41001,41002]).allocate()
        self.assertEqual(runner.call_count,1)
    def test_tcp_zero_tracker_collision_model_only(self):
        # Literal-key model of upstream UpdateReverseConfig; not an ADB/device reproducer.
        tracked={};tracked['tcp:0']='tcp:50001';tracked['tcp:0']='tcp:50002'
        self.assertNotIn('tcp:50001',tracked.values())
        tracked={'tcp:41001':'tcp:50001','tcp:41002':'tcp:50002'};tracked.pop('tcp:41002')
        self.assertIn('tcp:50001',tracked.values())

class ReservationTests(unittest.TestCase):
    def test_disconnect_retains_reservation_until_final_cleanup(self):
        lease=Mock();lease.quarantine.exists.return_value=False
        r=Reservation('synthetic',lambda _:lease);r.acquire();r.acquire();r.release(clean=True)
        lease.acquire.assert_called_once();lease.release.assert_not_called()
        r.finish(clean=True);lease.release.assert_called_once_with(clean=True)
    def test_poison_blocks_reconnect(self):
        lease=Mock();lease.quarantine.exists.return_value=True
        r=Reservation('synthetic',lambda _:lease);r.acquire()
        with self.assertRaises(RuntimeError):r.acquire()
    def test_standalone_busy_lease_prevents_all_device_work(self):
        lease=Mock();lease.acquire.side_effect=RuntimeError('busy');fixture=Mock()
        with self.assertRaises(RuntimeError):asyncio.run(main(SimpleNamespace(device='synthetic'),lambda _:lease,fixture))
        fixture.assert_not_called();lease.release.assert_not_called()
    def test_standalone_failure_preserves_recovery_marker(self):
        lease=Mock()
        async def fixture(args):raise OSError('injected')
        with self.assertRaises(OSError):asyncio.run(main(SimpleNamespace(device='synthetic'),lambda _:lease,fixture))
        lease.poison.assert_called_once();lease.release.assert_called_once_with(clean=False)
