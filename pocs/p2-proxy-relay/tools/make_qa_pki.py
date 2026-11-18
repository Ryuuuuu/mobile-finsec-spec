from pathlib import Path
from datetime import datetime,timedelta,timezone
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import argparse
parser=argparse.ArgumentParser(description='Create disposable localhost-only TLS assets; never installs trust')
parser.add_argument('--output',type=Path,required=True)
root=parser.parse_args().output
root.mkdir(parents=True,exist_ok=False)
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'P2 Disposable Test CA')]);now=datetime.now(timezone.utc)
ca=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True).sign(key,hashes.SHA256())
server=rsa.generate_private_key(public_exponent=65537,key_size=2048)
cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])).issuer_name(name).public_key(server.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3)).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(key,hashes.SHA256())
(root/'assets').mkdir(exist_ok=True)
(root/'assets/qa-ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
(root/'server.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
(root/'server.key').write_bytes(server.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
print('Generated private three-day localhost test PKI; no trust store modified')
