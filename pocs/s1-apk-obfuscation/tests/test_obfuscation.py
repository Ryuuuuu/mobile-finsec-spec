import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import obfuscation as o
from fixtures import create


class ObfuscationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def result(self,review=None,variant='pass',observations=None):
        apk,default=create(self.root/'fixture',variant,observations)
        info,entries=o.inventory(apk)
        return o.evaluate(info,entries,review or default)

    def test_three_variants_three_cli_runs_each(self):
        for variant in ('pass','fail','inconclusive'):
            apk,_=create(self.root/variant,variant)
            for index in range(3):
                output=self.root/f'{variant}-{index}.json'
                proc=subprocess.run([sys.executable,'-m','obfuscation','evaluate','--apk',str(apk),
                    '--review',str(apk.parent/'review.json'),'--output',str(output)],capture_output=True,timeout=10)
                self.assertEqual(proc.returncode,0,proc.stderr)
                result=json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(result['verdict'],variant)
                self.assertTrue(result['synthetic'])

    def test_inventory_cannot_pass_even_with_fixture(self):
        apk,_=create(self.root/'f')
        info,_=o.inventory(apk)
        self.assertEqual(o.base(info,False)['verdict'],'inconclusive')
        self.assertEqual(info['dex_entries'],1)

    def test_one_dimension_never_decides(self):
        apk,review=create(self.root/'f')
        info,entries=o.inventory(apk)
        for ref in review['evidence']:
            single=dict(review,evidence=[ref])
            self.assertEqual(o.evaluate(info,entries,single)['verdict'],'inconclusive')

    def test_mixed_findings_inconclusive(self):
        apk,review=create(self.root/'f','pass')
        info,entries=o.inventory(apk)
        ref=review['evidence'][1]
        obs=o.decode(entries[ref['entry']]);obs['finding']='violates'
        entries[ref['entry']]=json.dumps(obs).encode();ref['sha256']=o.digest(entries[ref['entry']])
        self.assertEqual(o.evaluate(info,entries,review)['verdict'],'inconclusive')

    def test_missing_policy_scope_or_hash_never_passes(self):
        apk,review=create(self.root/'f')
        info,entries=o.inventory(apk)
        for field in ('policy','selected_scopes','artifact_sha256'):
            altered=deepcopy(review);altered.pop(field)
            self.assertEqual(o.evaluate(info,entries,altered)['verdict'],'inconclusive')

    def test_missing_tampered_or_reused_evidence(self):
        apk,review=create(self.root/'f');info,entries=o.inventory(apk)
        for kind in ('missing','hash','reuse'):
            altered=deepcopy(review)
            if kind=='missing':altered['evidence'][0]['entry']='missing'
            elif kind=='hash':altered['evidence'][0]['sha256']='0'*64
            else:altered['evidence'][1]=deepcopy(altered['evidence'][0])
            self.assertEqual(o.evaluate(info,entries,altered)['verdict'],'inconclusive')

    def test_tool_scope_status_conflict_or_unknown(self):
        apk,review=create(self.root/'f');info,original=o.inventory(apk)
        for field,value in (('tool','unknown'),('scope','other'),('status','failed'),
                            ('dimension','identifiers'),('finding','unknown')):
            entries=dict(original);altered=deepcopy(review);ref=altered['evidence'][1]
            obs=o.decode(entries[ref['entry']]);obs[field]=value
            entries[ref['entry']]=json.dumps(obs).encode();ref['sha256']=o.digest(entries[ref['entry']])
            self.assertEqual(o.evaluate(info,entries,altered)['verdict'],'inconclusive')

    def test_fail_scope_preserved_with_incomplete_scope(self):
        apk,review=create(self.root/'f','fail');info,entries=o.inventory(apk)
        review['selected_scopes'].append('missing_scope')
        self.assertEqual(o.evaluate(info,entries,review)['verdict'],'fail')

    def test_pass_scope_cannot_cover_missing_scope(self):
        apk,review=create(self.root/'f');info,entries=o.inventory(apk)
        review['selected_scopes'].append('missing_scope')
        self.assertEqual(o.evaluate(info,entries,review)['verdict'],'inconclusive')

    def test_unselected_evidence_does_not_count(self):
        apk,review=create(self.root/'f','fail');info,entries=o.inventory(apk)
        review['selected_scopes']=['different_scope']
        self.assertEqual(o.evaluate(info,entries,review)['verdict'],'inconclusive')

    def test_nonfixture_cannot_use_synthetic_review(self):
        apk,review=create(self.root/'f',marker=False);info,entries=o.inventory(apk)
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_FIXTURE_REQUIRED'):
            o.evaluate(info,entries,review)

    def test_unsafe_archives_rejected_without_extraction(self):
        for index,names in enumerate((['../escape'],['/absolute'],['a\\b'],['a','a'],['C:drive'])):
            apk=self.root/f'unsafe-{index}.apk'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with zipfile.ZipFile(apk,'w') as z:
                    z.writestr('AndroidManifest.xml','fixture')
                    for name in names:z.writestr(name,'data')
            if names == ['a\\b']:
                # Windows ZipInfo normalizes backslashes while writing; inject raw ZIP names.
                apk.write_bytes(apk.read_bytes().replace(b'a/b', b'a\\b'))
            with self.subTest(names=names), self.assertRaises(ValueError):
                o.inventory(apk)
        self.assertFalse((self.root/'escape').exists())

    def test_size_and_zip_expansion_limits(self):
        apk,_=create(self.root/'f')
        with patch.object(o,'MAX_APK',10),self.assertRaises(ValueError):o.inventory(apk)
        bomb=self.root/'bomb.apk'
        with zipfile.ZipFile(bomb,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('AndroidManifest.xml',b'x'*100000)
        with self.assertRaises(ValueError):o.inventory(bomb)

    def test_multidex_names_do_not_claim_bytecode_validation(self):
        apk=self.root/'multi.apk'
        with zipfile.ZipFile(apk,'w') as z:
            z.writestr('AndroidManifest.xml','fixture')
            for name in ('classes.dex','classes2.dex','classes10.dex','classes1.dex','classes0.dex'):
                z.writestr(name,'not real DEX')
        info,_=o.inventory(apk)
        self.assertEqual(info['dex_entries'],3)
        self.assertEqual(o.base(info,False)['verdict'],'inconclusive')

    def test_duplicate_json_and_nonfinite_rejected(self):
        for data in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            with self.assertRaises(ValueError):o.decode(data)

    def test_existing_output_is_preserved(self):
        apk,_=create(self.root/'f');out=self.root/'result.json';out.write_bytes(b'original')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(o.main(['inspect','--apk',str(apk),'--output',str(out)]),2)
        self.assertEqual(out.read_bytes(),b'original')

    def test_bad_input_fails_inconclusive_without_raw_text(self):
        apk=self.root/'bad.apk';apk.write_bytes(b'PRIVATE_SENTINEL')
        out=self.root/'result.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(o.main(['inspect','--apk',str(apk),'--output',str(out)]),2)
        result=json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result['execution_status'],'failed')
        self.assertEqual(result['verdict'],'inconclusive')
        self.assertNotIn('PRIVATE_SENTINEL',out.read_text(encoding='utf-8'))

    def test_schema_and_marker_validation(self):
        apk,review=create(self.root/'f');info,entries=o.inventory(apk)
        for field,value in (('schema_version','2'),('synthetic',False)):
            changed=dict(review);changed[field]=value
            with self.assertRaises(ValueError):o.evaluate(info,entries,changed)

    def test_deterministic_fixture_bytes(self):
        a,_=create(self.root/'a');b,_=create(self.root/'b')
        self.assertEqual(a.read_bytes(),b.read_bytes())


if __name__=='__main__':unittest.main()
