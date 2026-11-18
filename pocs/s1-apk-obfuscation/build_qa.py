"""Build authored unsigned real-DEX APK pair using existing official SDK tools."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jdk',type=Path,required=True)
    p.add_argument('--sdk',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    qa=Path(__file__).parent/'qa'
    java=args.jdk/'bin/java.exe';javac=args.jdk/'bin/javac.exe'
    android=args.sdk/'platforms/android-35/android.jar'
    build=args.sdk/'build-tools/35.0.0';tools=args.sdk/'cmdline-tools/19.0'
    records=[]
    def run(name,cmd):
        result=subprocess.run([str(v) for v in cmd],capture_output=True,timeout=120)
        (out/(name+'.stdout')).write_bytes(result.stdout)
        (out/(name+'.stderr')).write_bytes(result.stderr)
        records.append(dict(step=name,exit=result.returncode))
        if result.returncode:raise RuntimeError('BUILD_FAILED_'+name)
    run('java-version',[java,'-version'])
    run('d8-version',[java,'-cp',build/'lib/d8.jar','com.android.tools.r8.D8','--version'])
    classes=out/'classes';classes.mkdir()
    run('javac',[javac,'-source','8','-target','8','-classpath',android,'-d',classes,*sorted(qa.rglob('*.java'))])
    jar=out/'input.jar'
    with zipfile.ZipFile(jar,'x') as archive:
        for path in sorted(classes.rglob('*.class')):archive.write(path,path.relative_to(classes).as_posix())
    for variant,compiler,classpath,extra in (
        ('plain','R8',tools/'lib/r8.jar',['--pg-conf',qa/'plain.pro','--pg-map-output',out/'plain-mapping.txt']),
        ('renamed','R8',tools/'lib/r8.jar',['--pg-conf',qa/'rename.pro','--pg-map-output',out/'mapping.txt'])):
        dest=out/variant;dest.mkdir()
        run(variant+'-version',[java,'-cp',classpath,'com.android.tools.r8.'+compiler,'--version'])
        run(variant,[java,'-cp',classpath,'com.android.tools.r8.'+compiler,'--release','--min-api','26',
            '--lib',android,'--output',dest,*extra,jar])
    stub=out/'manifest.apk'
    run('aapt',[build/'aapt.exe','package','-f','-M',qa/'AndroidManifest.xml','-I',android,'-F',stub])
    for variant in ('plain','renamed'):
        apk=out/(variant+'.apk')
        with zipfile.ZipFile(stub) as source,zipfile.ZipFile(apk,'x',compression=zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():target.writestr(name,source.read(name))
            for dex in sorted((out/variant).glob('*.dex')):target.write(dex,dex.name)
        run(variant+'-badging',[build/'aapt.exe','dump','badging',apk])
    hashes={path.relative_to(qa).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in qa.rglob('*') if path.is_file()}
    (out/'build.json').write_text(json.dumps(dict(source_hashes=hashes,steps=records,unsigned=True,device_execution=False),indent=2),encoding='utf-8')
    print('Built plain.apk and renamed.apk; unsigned, not installed.')


if __name__=='__main__':main()
