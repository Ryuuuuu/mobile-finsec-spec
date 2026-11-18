"""Ephemeral localhost-only test PKI; never use or commit a real certificate/key."""
from pathlib import Path
import shutil
import importlib.util
import sys
import ssl
import subprocess
import unittest


class TLSFixture:
    def __init__(self, directory):
        executable = shutil.which('openssl')
        if executable is None:
            if importlib.util.find_spec('cryptography') is None:
                raise unittest.SkipTest('OpenSSL CLI or requirements-device.txt needed for ephemeral test PKI')
            self.directory = Path(directory)
            generated = self.directory / 'python-pki'
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'tools/make_qa_pki.py'),
                            '--output', str(generated)], check=True, capture_output=True, timeout=20)
            self.ca = generated / 'assets/qa-ca.pem'
            self.cert = generated / 'server.pem'
            self.key = generated / 'server.key'
            return
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ca = self.directory / 'synthetic-ca.pem'
        self.ca_key = self.directory / 'synthetic-ca.key'
        self.cert = self.directory / 'synthetic-localhost.pem'
        self.key = self.directory / 'synthetic-localhost.key'
        csr = self.directory / 'synthetic-localhost.csr'
        extensions = self.directory / 'synthetic-localhost.ext'
        extensions.write_text(
            'basicConstraints=critical,CA:FALSE\n'
            'keyUsage=critical,digitalSignature,keyEncipherment\n'
            'extendedKeyUsage=serverAuth\n'
            'subjectAltName=DNS:localhost,IP:127.0.0.1\n'
            'subjectKeyIdentifier=hash\n'
            'authorityKeyIdentifier=keyid,issuer\n', encoding='ascii')

        def run(*args):
            subprocess.run([executable, *map(str, args)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

        run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-keyout', self.ca_key, '-out', self.ca, '-subj', '/CN=P2 Synthetic Test CA',
            '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', self.key,
            '-out', csr, '-subj', '/CN=localhost')
        run('x509', '-req', '-in', csr, '-CA', self.ca, '-CAkey', self.ca_key,
            '-CAcreateserial', '-out', self.cert, '-days', '1', '-extfile', extensions)
        self.ca_key.chmod(0o600)
        self.key.chmod(0o600)

    def server_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_alpn_protocols(['http/1.1'])
        context.load_cert_chain(self.cert, self.key, password='')
        return context

    def client_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_alpn_protocols(['http/1.1'])
        context.load_verify_locations(cafile=self.ca)
        return context
