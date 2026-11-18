"""Generate reproducible APK-shaped contract fixtures, NOT installable APKs."""
import argparse
import json
from pathlib import Path
import zipfile
from obfuscation import MARKER, POLICY, digest


def create(folder, variant='pass', observations=None, marker=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    apk = folder/'synthetic.apk'
    review = dict(schema_version='1.0', synthetic=True, policy=POLICY,
                  selected_scopes=['important_logic'], evidence=[])
    findings = {'pass':('supports','supports'), 'fail':('violates','violates'),
                'inconclusive':('supports','unknown')}[variant]
    observations = observations if observations is not None else [dict(
        synthetic=True, scope='important_logic', tool='synthetic-review/1', status='completed',
        dimension=dim, finding=value) for dim,value in zip(('identifiers','logic_readability'),findings)]
    with zipfile.ZipFile(apk, 'x', compression=zipfile.ZIP_STORED) as archive:
        def put(name, data):
            archive.writestr(zipfile.ZipInfo(name, date_time=(2020,1,1,0,0,0)), data)
        put('AndroidManifest.xml', b'<synthetic-not-installable/>')
        put('classes.dex', b'NOT A VALID DEX: synthetic evidence contract only')
        if marker:
            put('assets/CHK15-SYNTHETIC', MARKER)
        for index, observation in enumerate(observations):
            data=json.dumps(observation, sort_keys=True).encode()
            name=f'assets/review-{index}.json'
            put(name,data)
            review['evidence'].append(dict(scope=observation['scope'],entry=name,sha256=digest(data)))
    review['artifact_sha256']=digest(apk.read_bytes())
    (folder/'review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
    return apk,review


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--variant',choices=('pass','fail','inconclusive'),default='pass')
    args=parser.parse_args()
    create(args.output,args.variant)
