"""Disposable PKI generation safety; does not install certificates."""
import importlib.util,subprocess,sys,tempfile,unittest
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('cryptography'), 'optional device PKI dependency')
class DevicePKITest(unittest.TestCase):
    def test_localhost_identity_short_validity_and_no_overwrite(self):
        from cryptography import x509
        from cryptography.x509.oid import ExtendedKeyUsageOID
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'new-pki'
            tool=Path(__file__).resolve().parents[1]/'tools/make_qa_pki.py'
            command=[sys.executable,str(tool),'--output',str(root)]
            subprocess.run(command,check=True,capture_output=True)
            original=(root/'server.key').read_bytes()
            cert=x509.load_pem_x509_certificate((root/'server.pem').read_bytes())
            self.assertEqual(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName),['localhost'])
            self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH,cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
            self.assertLessEqual((cert.not_valid_after_utc-cert.not_valid_before_utc).days,4)
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual((root/'server.key').read_bytes(),original)
