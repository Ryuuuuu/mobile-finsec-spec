"""Synthetic coverage/fault cases; separate from actual SDK fixture acceptance."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import dex_extract as d
import obfuscation as o
from fixtures import create
from test_dex_extract import PACKAGES,SMALI

OTHER='C d 1 1 40 qa.Other\nM d 1 1 40 qa.Other void show(android.webkit.WebView)\n'
OTHER_SMALI='.class public Lqa/Other;\n.method public show()V\n.end method\n'


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tools=self.root/'tools';(self.tools/'lib').mkdir(parents=True)
        (self.tools/'source.properties').write_text('Pkg.Revision=19.0\n')
        (self.tools/'lib/apkanalyzer-classpath.jar').write_bytes(b'FAKE NOT EXECUTED')
        self.apk,_=create(self.root/'fixture')
        with zipfile.ZipFile(self.apk,'a') as z:
            z.writestr('classes2.dex',b'SYNTHETIC PLACEHOLDER')
            z.writestr('lib/x86/libmarker.so',b'NOT ELF')
            z.writestr('assets/index.html',b'QA')
            z.writestr('assets/hidden.dex',b'NOT ANALYZED')

    def run_case(self,outputs,selected=('qa.Logic','qa.Other')):
        with patch.object(d,'run_tool',side_effect=outputs):
            return d.analyze(self.apk,Path('not-executed'),self.tools,list(selected),self.root/'out')

    def test_each_dex_and_selected_provenance_with_explicit_gaps(self):
        r=self.run_case(['classes.dex\nclasses2.dex',PACKAGES,OTHER,SMALI,OTHER_SMALI])
        self.assertEqual(r['execution_status'],'completed');self.assertEqual(r['verdict'],'inconclusive')
        self.assertEqual([v['dex_file'] for v in r['selected']],['classes.dex','classes2.dex'])
        self.assertEqual(r['coverage']['native']['status'],'not_analyzed')
        self.assertEqual(r['coverage']['native']['entry_count'],1)
        self.assertEqual(r['coverage']['webview']['reference_signal'],'observed')
        self.assertEqual(r['coverage']['webview']['status'],'not_analyzed')
        self.assertEqual(r['coverage']['resources']['web_asset_count'],1)
        self.assertEqual(r['coverage']['nonstandard_dex_entries'],['assets/hidden.dex'])
        self.assertEqual(r['coverage']['whole_application'],'not_assessed')

    def test_second_dex_failure_preserves_first_and_lists_missing_scope(self):
        r=self.run_case(['classes.dex\nclasses2.dex',PACKAGES,d.AnalysisError('TOOL_FAILED')])
        self.assertEqual(r['failure_stage'],'dex-packages:classes2.dex')
        self.assertEqual(len(r['dex_files']),1)
        self.assertEqual(r['coverage']['dex_defined'],'partial')
        self.assertEqual(r['coverage']['unextracted_selected_classes'],['qa.Logic','qa.Other'])

    def test_second_smali_timeout_preserves_first_without_completing(self):
        r=self.run_case(['classes.dex\nclasses2.dex',PACKAGES,OTHER,SMALI,d.AnalysisError('TOOL_TIMEOUT')])
        self.assertEqual(r['execution_status'],'failed');self.assertEqual(r['verdict'],'inconclusive')
        self.assertEqual(r['coverage']['selected_smali'],'partial')
        self.assertEqual(r['coverage']['unextracted_selected_classes'],['qa.Other'])
        self.assertEqual(len(r['selected']),1)

    def test_duplicate_class_across_dex_is_rejected(self):
        r=self.run_case(['classes.dex\nclasses2.dex',PACKAGES,PACKAGES])
        self.assertEqual(r['reason_code'],'DUPLICATE_CLASS_ACROSS_DEX')

    def test_missing_dex_from_tool_list_not_silently_omitted(self):
        r=self.run_case(['classes.dex'])
        self.assertEqual(r['reason_code'],'DEX_LIST_MISMATCH')
        self.assertEqual(r['coverage']['dex_inventory'],'not_run')

    def test_oversize_input_records_limit_and_does_not_start_tool(self):
        with patch.object(o,'MAX_APK',10),patch.object(d,'run_tool') as tool:
            r=d.analyze(self.apk,Path('not-executed'),self.tools,['qa.Logic'],self.root/'out')
        tool.assert_not_called()
        self.assertEqual(r['reason_code'],'INPUT_LIMIT')
        self.assertEqual(r['failure_stage'],'inventory')
        self.assertEqual(r['coverage']['native']['entry_count'],None)

    def test_excess_dex_count_fails_before_per_dex_analysis(self):
        with zipfile.ZipFile(self.apk,'a') as z:
            for index in range(3,18):z.writestr(f'classes{index}.dex',b'PLACEHOLDER')
        names='classes.dex\n'+'\n'.join(f'classes{i}.dex' for i in range(2,18))
        r=self.run_case([names])
        self.assertEqual(r['reason_code'],'DEX_COUNT_LIMIT')
        self.assertNotIn('dex_files',r)

    def test_no_observed_webview_signature_is_not_an_absence_claim(self):
        other='C d 1 1 40 qa.Other\nM d 1 1 40 qa.Other void show()\n'
        r=self.run_case(['classes.dex\nclasses2.dex',PACKAGES,other,SMALI,OTHER_SMALI])
        self.assertEqual(r['coverage']['webview']['reference_signal'],'not_observed_in_defined_signatures')
        self.assertEqual(r['coverage']['webview']['status'],'not_analyzed')

    def test_total_budget_expires_without_dispatch(self):
        with patch.object(d.time,'monotonic',side_effect=[0,121]),patch.object(d,'run_tool') as tool:
            r=d.analyze(self.apk,Path('not-executed'),self.tools,['qa.Logic'],self.root/'out')
        tool.assert_not_called();self.assertEqual(r['reason_code'],'ANALYSIS_TIMEOUT')


if __name__=='__main__':unittest.main()
