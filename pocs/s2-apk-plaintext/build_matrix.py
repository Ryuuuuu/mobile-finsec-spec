"""Build a local authored multidex/encoding matrix; never installs an APK."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from scan import MARKERS, scan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('jdk', 'sdk', 'base', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    classes = out / 'classes'; classes.mkdir()
    dex = out / 'dex'; dex.mkdir()
    source = out / 'Extra.java'
    source.write_text('package qa.s2; public class Extra { public static String sample() { return "QA_PLAINTEXT_DEMO_TOKEN_001"; } }')
    android = args.sdk / 'platforms/android-35/android.jar'
    def run(label, command):
        r = subprocess.run([str(x) for x in command], capture_output=True, timeout=60)
        (out / (label + '.stdout')).write_bytes(r.stdout)
        (out / (label + '.stderr')).write_bytes(r.stderr)
        if r.returncode:
            raise RuntimeError('QA_BUILD_FAILED')
    run('javac', [args.jdk / 'bin/javac.exe', '-source', '8', '-target', '8', '-d', classes, source])
    jar = out / 'extra.jar'
    with zipfile.ZipFile(jar, 'x') as z:
        for file in classes.rglob('*.class'):
            z.write(file, file.relative_to(classes).as_posix())
    run('d8', [args.jdk / 'bin/java.exe', '-cp', args.sdk / 'cmdline-tools/19.0/lib/r8.jar',
               'com.android.tools.r8.D8', '--release', '--min-api', '26', '--lib', android,
               '--output', dex, jar])
    marker = MARKERS['demo_token']
    apk = out / 'matrix.apk'
    with zipfile.ZipFile(args.base) as src, zipfile.ZipFile(apk, 'x', compression=zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.write(dex / 'classes.dex', 'classes2.dex')
        for encoding in ('utf-8', 'utf-16le', 'utf-16be'):
            dst.writestr('assets/' + encoding + '.txt', marker.decode().encode(encoding))
        dst.writestr('res/raw/synthetic.bin', b'\xff\x00\x01' + marker + b'\xff')
        dst.writestr('assets/base64.txt', base64.b64encode(marker))
        dst.writestr('assets/nested.gz', gzip.compress(marker, mtime=0))
    result = scan(apk, out / 'scan')
    assert result['execution_status'] == 'completed'
    assert result['artifact']['dex_entries'] == 2
    expected = {'classes.dex': ('qa_status', 'utf-8'), 'classes2.dex': ('demo_token', 'utf-8'),
                'res/raw/synthetic.bin': ('demo_token', 'utf-8')}
    expected.update({'assets/' + e + '.txt': ('demo_token', e) for e in ('utf-8', 'utf-16le', 'utf-16be')})
    with zipfile.ZipFile(apk) as z:
        names = {hashlib.sha256(n.encode()).hexdigest(): n for n in z.namelist()}
        actual = {}
        for hit in result['matches']:
            name = names[hit['entry_id']]
            value = MARKERS[hit['marker_id']].decode().encode(hit['representation'])
            data = z.read(name)
            assert data[hit['offset']:hit['offset'] + hit['length']] == value
            assert hashlib.sha256(data).hexdigest() == hit['entry_sha256']
            assert name not in actual
            actual[name] = hit['marker_id'], hit['representation']
        assert actual == expected
    (out / 'validation.json').write_text(json.dumps(dict(status='passed', expected_hits=6,
        actual_hits=len(result['matches']), dex_entries=2, device='not_run')))
    print('PASS: real two-DEX QA APK, six exact representation/offset/hash matches; base64/gzip unexamined')


if __name__ == '__main__':
    main()
