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

    def test_encoding_is_not_decoded(self):
        marker = MARKERS['demo_token']
        result = self.run_scan(base64.b64encode(marker) + b'|' + marker.decode().encode('utf-16le'))
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


if __name__ == '__main__':
    unittest.main()
