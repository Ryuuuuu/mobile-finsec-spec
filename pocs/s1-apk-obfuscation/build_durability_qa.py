"""Construct real multidex/large QA APKs and a separate synthetic native-path case."""
import argparse
from pathlib import Path
import subprocess
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('jdk','sdk','base','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    classes=out/'classes';classes.mkdir();dex=out/'extra';dex.mkdir()
    source=Path(__file__).parent/'qa_extra/ExtraSurface.java'
    java=args.jdk/'bin/java.exe';android=args.sdk/'platforms/android-35/android.jar'
    def run(label,cmd):
        proc=subprocess.run([str(x) for x in cmd],capture_output=True,timeout=60)
        (out/(label+'.stdout')).write_bytes(proc.stdout);(out/(label+'.stderr')).write_bytes(proc.stderr)
        if proc.returncode:raise RuntimeError('QA_BUILD_FAILED')
    run('javac',[args.jdk/'bin/javac.exe','-source','8','-target','8','-classpath',android,'-d',classes,source])
    jar=out/'extra.jar'
    with zipfile.ZipFile(jar,'x') as z:
        for path in classes.rglob('*.class'):z.write(path,path.relative_to(classes).as_posix())
    run('d8',[java,'-cp',args.sdk/'cmdline-tools/19.0/lib/r8.jar','com.android.tools.r8.D8',
               '--release','--min-api','26','--lib',android,'--output',dex,jar])
    with zipfile.ZipFile(args.base) as z:base={name:z.read(name) for name in z.namelist()}
    for variant in ('multidex','large','native-marker','oversize'):
        with zipfile.ZipFile(out/(variant+'.apk'),'x',compression=zipfile.ZIP_STORED) as z:
            for name,data in base.items():z.writestr(name,data)
            z.write(dex/'classes.dex','classes2.dex')
            z.writestr('assets/qa.html','<html>QA authored fixture</html>')
            z.writestr('assets/qa.js','// QA asset only, not executed\n')
            if variant=='native-marker':
                z.writestr('lib/arm64-v8a/libqa_marker.so',b'SYNTHETIC PATH MARKER - NOT ELF OR NATIVE CODE')
            if variant in ('large','oversize'):
                for index in range(4 if variant=='large' else 6):
                    z.writestr(f'assets/padding-{index}.bin',b'QA_PADDING'*((6*1024*1024)//10))
    print('Created multidex, 24 MiB padded, synthetic native marker and oversize fixtures; no installation.')


if __name__=='__main__':main()
