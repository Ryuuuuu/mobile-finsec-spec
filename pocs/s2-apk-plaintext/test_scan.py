import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scan import scan, MARKERS, Limits, CHUNK, ResourceError


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def apk(self, payload=b'', name='assets/demo.txt', compression=zipfile.ZIP_STORED):
        path = self.root / 'qa.apk'
        with zipfile.ZipFile(path, 'w', compression=compression) as z:
            z.writestr('AndroidManifest.xml', b'synthetic-not-an-installable-apk')
            z.writestr(name, payload)
        return path

    def run_scan(self, payload=b'', **kwargs):
        return scan(self.apk(payload), self.root / 'out', **kwargs)

    def test_exact_evidence_and_no_context(self):
        marker = MARKERS['demo_token']
        payload = b'private-context:' + marker
        result = self.run_scan(payload)
        hit, = result['matches']
        self.assertEqual((hit['offset'], hit['length']), (16, len(marker)))
        self.assertEqual(hit['entry_sha256'], hashlib.sha256(payload).hexdigest())
        serialized = json.dumps(result)
        self.assertNotIn(marker.decode(), serialized)
        self.assertNotIn('private-context', serialized)
        self.assertEqual(result['commandline_observation'], 'not_run')
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['artifact']['artifact_sha256'],
                         hashlib.sha256((self.root / 'qa.apk').read_bytes()).hexdigest())

    def test_cross_chunk_and_no_overlap_duplicates(self):
        marker = MARKERS['demo_token']
        payload = b'x' * (CHUNK - 4) + marker + b'x' * CHUNK + marker
        result = self.run_scan(payload)
        self.assertEqual([m['offset'] for m in result['matches']],
                         [CHUNK - 4, 2 * CHUNK - 4 + len(marker)])

    def test_match_ending_at_chunk_boundary_not_duplicated(self):
        marker = MARKERS['qa_status']
        result = self.run_scan(b'x' * (CHUNK - len(marker)) + marker + b'x')
        self.assertEqual(len(result['matches']), 1)

    def test_no_match_is_not_safe(self):
        result = self.run_scan(b'ordinary')
        self.assertEqual(result['literal_observation'], 'not_observed')
        self.assertEqual(result['verdict'], 'inconclusive')

    def test_base64_is_not_decoded(self):
        marker = MARKERS['demo_token']
        result = self.run_scan(base64.b64encode(marker))
        self.assertEqual(result['matches'], [])

    def test_compressed_entry(self):
        result = scan(self.apk(MARKERS['qa_status'], compression=zipfile.ZIP_DEFLATED), self.root / 'out')
        self.assertEqual(result['literal_observation'], 'found')

    def test_cap_does_not_claim_complete(self):
        result = self.run_scan(MARKERS['qa_status'] * 5, max_matches=2)
        self.assertEqual(result['reason_code'], 'MATCH_LIMIT')
        self.assertEqual(result['coverage'], 'partial')
        self.assertNotEqual(result['literal_observation'], 'not_observed')

    def test_previous_chunk_evidence_survives_cap(self):
        result = self.run_scan(MARKERS['qa_status'] + b'x' * CHUNK + MARKERS['qa_status'] * 3,
                               max_matches=2)
        self.assertEqual(result['literal_observation'], 'found')
        self.assertEqual(result['matches'][0]['offset'], 0)
        self.assertEqual(result['coverage'], 'partial')

    def test_timeout(self):
        with patch('scan.time_guard', side_effect=ResourceError('ANALYSIS_TIMEOUT')):
            result = self.run_scan(MARKERS['qa_status'])
        self.assertEqual(result['reason_code'], 'ANALYSIS_TIMEOUT')
        self.assertEqual(result['coverage'], 'partial')

    def test_unsafe_archive(self):
        result = scan(self.apk(MARKERS['qa_status'], '../escape'), self.root / 'out')
        self.assertEqual(result['reason_code'], 'UNSAFE_ARCHIVE')
        self.assertEqual(result['coverage'], 'not_started')

    def test_expansion_bomb(self):
        result = scan(self.apk(b'0' * 1000000, compression=zipfile.ZIP_DEFLATED), self.root / 'out')
        self.assertEqual(result['reason_code'], 'EXPANSION_LIMIT')

    def test_input_limit(self):
        result = self.run_scan(b'x' * (1024 * 1024), limits=Limits(apk_mib=1))
        self.assertEqual(result['reason_code'], 'INPUT_LIMIT')

    def test_existing_output_preserved(self):
        self.run_scan()
        with self.assertRaises(FileExistsError):
            scan(self.root / 'qa.apk', self.root / 'out')

    def test_invalid_budget_no_output(self):
        with self.assertRaises(ResourceError):
            self.run_scan(limits=Limits(apk_mib=512, disk_mib=128))
        self.assertFalse((self.root / 'out').exists())

    def test_result_storage_failure_is_not_success(self):
        with patch('scan.storage_guard', side_effect=ResourceError('DISK_FREE_LIMIT')):
            with self.assertRaises(ResourceError):
                self.run_scan()
        self.assertFalse((self.root / 'out' / 'result.json').exists())

    def test_utf16_both_orders_cross_chunk(self):
        for encoding in ('utf-16le', 'utf-16be'):
            with self.subTest(encoding=encoding):
                marker = MARKERS['demo_token'].decode().encode(encoding)
                p = self.apk(b'x' * (CHUNK - 3) + marker)
                result = scan(p, self.root / encoding)
                hit, = result['matches']
                self.assertEqual(hit['representation'], encoding)
                self.assertEqual(hit['offset'], CHUNK - 3)
                self.assertEqual(hit['length'], len(marker))

    def test_sensitive_entry_name_not_serialized(self):
        result = scan(self.apk(MARKERS['qa_status'], 'assets/PRIVATE_ACCOUNT_NAME'), self.root / 'out')
        self.assertNotIn('PRIVATE_ACCOUNT_NAME', json.dumps(result))
        self.assertEqual(result['matches'][0]['entry_id'],
                         hashlib.sha256(b'assets/PRIVATE_ACCOUNT_NAME').hexdigest())

    def test_external_error_text_redacted(self):
        import zlib
        for index, error in enumerate((ResourceError('PRIVATE_SECRET'), zlib.error('PRIVATE_SECRET'),
                                       EOFError('PRIVATE_SECRET'), NotImplementedError('PRIVATE_SECRET'))):
            with patch('scan.snapshot_inventory', side_effect=error):
                result = scan(self.apk(), self.root / str(index))
            self.assertNotIn('PRIVATE_SECRET', json.dumps(result))
            self.assertEqual(result['execution_status'], 'failed')
            self.assertEqual(result['reason_code'], 'INPUT_OR_SCAN_ERROR')

    def test_invalid_zip_no_false_completion(self):
        path = self.root / 'broken.apk'
        path.write_bytes(b'not a ZIP')
        result = scan(path, self.root / 'out')
        self.assertEqual(result['coverage'], 'not_started')
        self.assertEqual(result['literal_observation'], 'unknown')

    def test_crc_damage_is_failure(self):
        path = self.apk(MARKERS['demo_token'])
        data = path.read_bytes()
        data = data.replace(MARKERS['demo_token'], b'X' * len(MARKERS['demo_token']), 1)
        path.write_bytes(data)
        result = scan(path, self.root / 'out')
        self.assertEqual(result['execution_status'], 'failed')
        self.assertEqual(result['literal_observation'], 'unknown')

    def test_nested_gzip_not_decoded(self):
        import gzip
        result = self.run_scan(gzip.compress(MARKERS['demo_token'], mtime=0))
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['verdict'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
