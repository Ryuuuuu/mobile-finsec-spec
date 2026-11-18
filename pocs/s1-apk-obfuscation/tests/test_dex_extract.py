"""Parser doubles and actual local child-process fault tests, not SDK acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dex_extract as d
from fixtures import create

PACKAGES='P d 2 2 100 <TOTAL>\nC d 2 2 100 qa.Logic\nM d 1 1 40 qa.Logic void check(int)\nF d 0 0 8 qa.Logic int limit\n'
SMALI='.class public Lqa/Logic;\n.method public check(I)V\n    if-lez p1, :end\n    const-string v0, "QA"\n.end method\n'


class DexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_defined_parser_and_single_metric_is_not_verdict(self):
        value=d.parse_packages(PACKAGES)
        self.assertEqual(value['class_count'],1)
        self.assertEqual(value['method_count'],1)
        self.assertNotIn('verdict',value)

    def test_unknown_format_empty_duplicate_or_orphan_rejected(self):
        for text in ('garbage','',PACKAGES+'C d 1 1 10 qa.Logic\n',PACKAGES+'M d 1 1 10 other.Class x()\n'):
            with self.subTest(text=text),self.assertRaises(d.AnalysisError):d.parse_packages(text)

    def test_smali_scope_and_observations(self):
        self.assertEqual(d.smali_summary(SMALI,'qa.Logic')['conditional_instructions'],1)
        with self.assertRaises(d.AnalysisError):d.smali_summary(SMALI,'qa.Other')

    def test_real_child_timeout_is_reaped(self):
        original=subprocess.Popen;children=[]
        def capture(*args,**kwargs):
            child=original(*args,**kwargs);children.append(child);return child
        with patch.object(d.subprocess,'Popen',side_effect=capture):
            with self.assertRaisesRegex(d.AnalysisError,'TOOL_TIMEOUT'):
                d.run_tool([sys.executable,'-c','import time; time.sleep(10)'],self.root,'timeout',timeout=0.1)
        self.assertIsNotNone(children[0].poll())

    def test_real_child_output_limit_and_exit_error(self):
        with self.assertRaisesRegex(d.AnalysisError,'TOOL_OUTPUT_LIMIT'):
            d.run_tool([sys.executable,'-c','print("x"*10000)'],self.root,'large',limit=100)
        with self.assertRaisesRegex(d.AnalysisError,'TOOL_FAILED'):
            d.run_tool([sys.executable,'-c','raise SystemExit(3)'],self.root,'bad-exit')

    def setup_analysis(self):
        tools=self.root/'tools';(tools/'lib').mkdir(parents=True)
        (tools/'source.properties').write_text('Pkg.Revision=19.0\n',encoding='utf-8')
        (tools/'lib/apkanalyzer-classpath.jar').write_bytes(b'FAKE JAR NOT EXECUTED')
        apk,_=create(self.root/'fixture')
        return tools,apk

    def test_mock_extraction_remains_inconclusive_and_no_overwrite(self):
        tools,apk=self.setup_analysis()
        with patch.object(d,'run_tool',side_effect=['/classes.dex\n',PACKAGES,SMALI]):
            result=d.analyze(apk,Path('not-executed'),tools,['qa.Logic'],self.root/'out')
        self.assertEqual(result['execution_status'],'completed')
        self.assertEqual(result['verdict'],'inconclusive')
        with self.assertRaises(FileExistsError):d.analyze(apk,Path('none'),tools,['qa.Logic'],self.root/'out')

    def test_missing_class_or_dex_is_failed_inconclusive(self):
        tools,apk=self.setup_analysis()
        for index,outputs in enumerate((['',PACKAGES],['/classes.dex\n',PACKAGES])):
            with patch.object(d,'run_tool',side_effect=outputs):
                result=d.analyze(apk,Path('none'),tools,['qa.Missing'],self.root/f'out{index}')
            self.assertEqual(result['execution_status'],'failed')
            self.assertEqual(result['verdict'],'inconclusive')

    def test_bad_zip_and_tool_version_fail_closed(self):
        tools,apk=self.setup_analysis();apk.write_bytes(b'PRIVATE_BAD_ZIP')
        result=d.analyze(apk,Path('none'),tools,['qa.Logic'],self.root/'badzip')
        self.assertEqual(result['execution_status'],'failed')
        self.assertNotIn('PRIVATE_BAD_ZIP',json.dumps(result))
        (tools/'source.properties').write_text('Pkg.Revision=99\n')
        result=d.analyze(apk,Path('none'),tools,['qa.Logic'],self.root/'version')
        self.assertEqual(result['reason_code'],'UNSUPPORTED_TOOL_VERSION')

    def test_snapshot_isolated_from_later_source_change(self):
        tools,apk=self.setup_analysis();original=d.snapshot_inventory
        def changed(*args):
            result=original(*args)
            apk.write_bytes(b'later source change')
            return result
        with patch.object(d,'snapshot_inventory',side_effect=changed), patch.object(d,'run_tool',side_effect=['classes.dex',PACKAGES,SMALI]):
            result=d.analyze(apk,Path('none'),tools,['qa.Logic'],self.root/'changed')
        self.assertEqual(result['execution_status'],'completed')
        self.assertEqual(d.digest((self.root/'changed/input.apk').read_bytes()),result['inventory']['artifact_sha256'])
        self.assertNotEqual(d.digest(apk.read_bytes()),result['inventory']['artifact_sha256'])


if __name__=='__main__':unittest.main()
