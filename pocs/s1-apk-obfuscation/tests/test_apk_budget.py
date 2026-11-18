"""Synthetic archive, disk, deadline and memory-allocation budget tests."""
from pathlib import Path
from collections import namedtuple
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import patch
import zipfile

import apk_budget as b
import dex_extract as d


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.apk=self.root/'source.apk';self.out=self.root/'out';self.out.mkdir()

    def apk_with(self,bytes_count=1024,compression=zipfile.ZIP_STORED):
        with zipfile.ZipFile(self.apk,'w',compression=compression) as z:
            z.writestr('AndroidManifest.xml',b'fixture')
            z.writestr('assets/padding',b'x'*bytes_count)

    def snapshot(self,limits=None):
        return b.snapshot_inventory(self.apk,self.out,limits or b.Limits(),time.monotonic()+30)

    def test_budget_is_explicit_finite_and_consistent(self):
        self.assertEqual(b.Limits.from_dict({'apk_mib':64}).apk_mib,64)
        for config in ({'apk_mib':0},{'apk_mib':513},{'apk_mib':True},{'apk_mib':1.5},
                       {'unknown':1},{'disk_mib':6},{'compression_ratio':201},{'heap_mib':2048}):
            with self.subTest(config=config),self.assertRaises(b.ResourceError):b.Limits.from_dict(config)

    def test_archive_larger_than_selected_limit_needs_explicit_budget(self):
        self.apk_with(2*b.MIB)
        with self.assertRaisesRegex(b.ResourceError,'INPUT_LIMIT'):self.snapshot(b.Limits(apk_mib=1))
        self.assertFalse((self.out/'input.apk').exists())
        info,entries=self.snapshot(b.Limits(apk_mib=4))
        self.assertGreater(info['bytes'],2*b.MIB)
        self.assertIsInstance(entries['assets/padding'],dict)
        self.assertNotIn('content',entries['assets/padding'])

    def test_compression_bomb_rejected_before_entry_decompression(self):
        self.apk_with(2*b.MIB,zipfile.ZIP_DEFLATED)
        original=zipfile.ZipFile.open;opened=[]
        def observe(z,member,*args,**kwargs):
            opened.append(member.filename if hasattr(member,'filename') else member)
            return original(z,member,*args,**kwargs)
        with patch.object(zipfile.ZipFile,'open',new=observe),self.assertRaisesRegex(b.ResourceError,'EXPANSION_LIMIT'):
            self.snapshot()
        self.assertNotIn('assets/padding',opened)

    def test_expanded_and_entry_caps_remain_independent(self):
        self.apk_with(2*b.MIB)
        with self.assertRaisesRegex(b.ResourceError,'EXPANSION_LIMIT'):
            self.snapshot(b.Limits(entry_mib=1))

    def test_central_directory_is_bounded_before_zipfile_load(self):
        self.apk_with();data=bytearray(self.apk.read_bytes());offset=data.rfind(b'PK\x05\x06')
        struct.pack_into('<L',data,offset+12,5*b.MIB);self.apk.write_bytes(data)
        with patch.object(b.zipfile,'ZipFile') as loader,self.assertRaisesRegex(b.ResourceError,'CENTRAL_DIRECTORY_LIMIT'):
            self.snapshot()
        loader.assert_not_called()

    def test_entry_count_preflight_and_zip64_fail_closed(self):
        self.apk_with()
        with self.assertRaisesRegex(b.ResourceError,'ENTRY_LIMIT'):self.snapshot(b.Limits(max_entries=1))
        data=bytearray(self.apk.read_bytes());offset=data.rfind(b'PK\x05\x06')
        struct.pack_into('<HH',data,offset+8,65535,65535);self.apk.write_bytes(data)
        with self.assertRaisesRegex(b.ResourceError,'UNSUPPORTED_ZIP64'):b.central_preflight(self.apk,b.Limits())

    def test_low_free_disk_rejects_before_copy(self):
        self.apk_with();usage=namedtuple('usage','total used free')(100,100,0)
        with patch.object(b.shutil,'disk_usage',return_value=usage),self.assertRaisesRegex(b.ResourceError,'DISK_FREE_LIMIT'):
            self.snapshot()
        self.assertFalse((self.out/'input.apk').exists())

    def test_total_output_disk_budget_and_metadata_reserve(self):
        (self.out/'old.log').write_bytes(b'x'*(3*b.MIB))
        with self.assertRaisesRegex(b.ResourceError,'DISK_BUDGET_LIMIT'):
            b.storage_guard(self.out,b.Limits(apk_mib=1,disk_mib=6,tool_output_mib=1))

    def test_inventory_deadline_retains_partial_copy_without_completion(self):
        self.apk_with(2*b.MIB)
        with patch.object(b,'time_guard',side_effect=[None,b.ResourceError('ANALYSIS_TIMEOUT')]),self.assertRaisesRegex(b.ResourceError,'ANALYSIS_TIMEOUT'):
            self.snapshot()
        self.assertEqual((self.out/'input.apk').stat().st_size,b.CHUNK)

    def test_streaming_python_peak_not_proportional_to_archive_payload(self):
        with zipfile.ZipFile(self.apk,'w',compression=zipfile.ZIP_STORED) as z:
            z.writestr('AndroidManifest.xml',b'fixture')
            for index in range(3):z.writestr(f'assets/{index}',b'x'*(4*b.MIB))
        tracemalloc.start()
        try:
            info,entries=self.snapshot()
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertGreater(info['bytes'],12*b.MIB)
        self.assertLess(peak,6*b.MIB)  # Python allocations only, not JVM or process RSS.
        self.assertEqual(len(entries),4)

    def test_disk_failure_during_copy_keeps_only_partial_bytes(self):
        self.apk_with(2*b.MIB)
        with patch.object(b,'storage_guard',side_effect=[None,None,b.ResourceError('DISK_FREE_LIMIT')]), self.assertRaisesRegex(b.ResourceError,'DISK_FREE_LIMIT'):
            self.snapshot()
        self.assertEqual((self.out/'input.apk').stat().st_size,b.CHUNK)

    def test_disk_guard_stops_and_reaps_owned_child(self):
        original=subprocess.Popen;children=[]
        def track(*args,**kwargs):
            child=original(*args,**kwargs);children.append(child);return child
        with patch.object(d.subprocess,'Popen',side_effect=track), patch.object(b,'storage_guard',side_effect=[None,b.ResourceError('DISK_BUDGET_LIMIT')]):
            with self.assertRaisesRegex(b.ResourceError,'DISK_BUDGET_LIMIT'):
                d.run_tool([sys.executable,'-c','import time; time.sleep(10)'],self.out,'disk-stop',storage_check=lambda:b.storage_guard(self.out,b.Limits()))
        self.assertIsNotNone(children[0].poll())

    def test_result_storage_failure_never_publishes_completed_json(self):
        with patch.object(d,'storage_guard',side_effect=b.ResourceError('DISK_FREE_LIMIT')),self.assertRaises(b.ResourceError):
            d.save_result(self.out,{'execution_status':'completed'},b.Limits())
        self.assertFalse((self.out/'result.json').exists())
        self.assertTrue((self.out/'result.json.tmp').exists())

    def test_symbol_count_and_length_bounds(self):
        with self.assertRaisesRegex(d.AnalysisError,'SYMBOL_RECORD_LIMIT'):
            d.parse_packages('C d 1 1 10 qa.A\nM d 1 1 10 qa.A f()\n',max_records=1)
        with self.assertRaisesRegex(d.AnalysisError,'SYMBOL_LENGTH_LIMIT'):
            d.parse_packages('C d 1 1 10 '+('x'*513))


if __name__=='__main__':unittest.main()
