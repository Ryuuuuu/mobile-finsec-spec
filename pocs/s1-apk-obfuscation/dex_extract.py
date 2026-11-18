"""Actual official SDK DEX extraction; all security verdicts stay inconclusive."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import zipfile

from obfuscation import MAX_APK, bounded, digest, inventory


class AnalysisError(ValueError):
    pass


def run_tool(command, folder, label, timeout=30, limit=4*1024*1024):
    stdout=folder/(label+'.stdout');stderr=folder/(label+'.stderr')
    with stdout.open('xb') as out,stderr.open('xb') as err:
        child=subprocess.Popen([str(x) for x in command],stdout=out,stderr=err,shell=False)
        deadline=time.monotonic()+timeout
        try:
            while child.poll() is None:
                if stdout.stat().st_size+stderr.stat().st_size > limit:
                    raise AnalysisError('TOOL_OUTPUT_LIMIT')
                if time.monotonic()>deadline:
                    raise AnalysisError('TOOL_TIMEOUT')
                time.sleep(0.02)
            if stdout.stat().st_size+stderr.stat().st_size > limit:
                raise AnalysisError('TOOL_OUTPUT_LIMIT')
            if child.returncode:
                raise AnalysisError('TOOL_FAILED')
        finally:
            if child.poll() is None:child.kill()
            child.wait()
    return stdout.read_text(encoding='utf-8')


def parse_packages(text):
    classes=[];methods=[];fields=[]
    for line in text.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'([PCMF]) ([dkrx]) (\d+)\s+(\d+)\s+(\d+)\s+(.+)',line.strip())
        if not match:raise AnalysisError('UNSUPPORTED_PACKAGE_FORMAT')
        kind,state,defined,referenced,size,name=match.groups()
        if state!='d':continue
        if kind=='C':classes.append(name)
        elif kind=='M':methods.append(name)
        elif kind=='F':fields.append(name)
    if not classes or len(set(classes))!=len(classes):raise AnalysisError('NO_OR_DUPLICATE_CLASSES')
    for member in methods+fields:
        if member.split(' ',1)[0] not in classes:raise AnalysisError('MEMBER_WITHOUT_CLASS')
    return dict(classes=classes,methods=methods,fields=fields,
                class_count=len(classes),method_count=len(methods),field_count=len(fields),
                short_class_names=sum(len(c.rsplit('.',1)[-1])<=2 for c in classes))


def smali_summary(text, selected):
    descriptor='L'+selected.replace('.','/')+';'
    if not any(line.startswith('.class ') and line.endswith(' '+descriptor) for line in text.splitlines()):
        raise AnalysisError('SMALI_CLASS_MISMATCH')
    return dict(class_name=selected,method_bodies=len(re.findall(r'^\.method ',text,re.M)),
                conditional_instructions=len(re.findall(r'^\s+if-[a-z]+\b',text,re.M)),
                string_loads=len(re.findall(r'^\s+const-string(?:/jumbo)?\b',text,re.M)),
                source_name_present=bool(re.search(r'^\.source ',text,re.M)))


def analyze(apk, java, tools, selected, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result=dict(schema_version='1.0',check_id='CHK-15',synthetic=False,
                execution_status='failed',verdict='inconclusive',reason_code='ANALYSIS_INCOMPLETE',
                limitations=['Actual DEX evidence only; no security verdict or semantic readability scoring.',
                    'No signature verification, native/resource analysis, runtime or whole-app coverage.',
                    'Direct Java timeout management is not a hostile-parser OS sandbox.'])
    try:
        if (not selected or len(selected)>20 or len(set(selected))!=len(selected)
                or any(not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*',s) for s in selected)):
            raise AnalysisError('INVALID_CLASS_SELECTION')
        props=bounded(Path(tools)/'source.properties',16384).decode('utf-8')
        if 'Pkg.Revision=19.0' not in props.splitlines():raise AnalysisError('UNSUPPORTED_TOOL_VERSION')
        jar=Path(tools)/'lib/apkanalyzer-classpath.jar'
        result['tool']=dict(package='Android SDK Command-line Tools',revision='19.0',
            launcher_jar_sha256=digest(bounded(jar,MAX_APK)))
        info,entries=inventory(apk)
        result['inventory']=info
        raw=bounded(apk,MAX_APK)
        if digest(raw)!=info['artifact_sha256']:raise AnalysisError('ARTIFACT_CHANGED')
        snapshot=output/'input.apk';snapshot.write_bytes(raw)
        prefix=[java,'-Dcom.android.sdklib.toolsdir='+str(Path(tools).resolve()),'-cp',jar,
                'com.android.tools.apk.analyzer.ApkAnalyzerCli']
        dexlist=run_tool([*prefix,'dex','list',snapshot],output,'dex-list')
        dexnames=[line.strip().lstrip('/') for line in dexlist.splitlines() if line.strip()]
        expected=sorted(n for n in entries if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex',n))
        if not dexnames or sorted(dexnames)!=expected:raise AnalysisError('DEX_LIST_MISMATCH')
        package_text=run_tool([*prefix,'dex','packages','--defined-only',snapshot],output,'packages')
        result['defined']=parse_packages(package_text)
        if any(name not in result['defined']['classes'] for name in selected):raise AnalysisError('SELECTED_CLASS_MISSING')
        result['selected']=[]
        for index,name in enumerate(selected):
            text=run_tool([*prefix,'dex','code','--class',name,snapshot],output,f'code-{index}')
            result['selected'].append(smali_summary(text,name))
        result.update(execution_status='completed',reason_code='DEX_EVIDENCE_NOT_SECURITY_VERDICT')
    except (OSError,ValueError,TypeError,RuntimeError,zipfile.BadZipFile,NotImplementedError) as exc:
        result['reason_code']=str(exc) if isinstance(exc,AnalysisError) else 'INPUT_OR_TOOL_ERROR'
    def file_hash(path):
        hasher=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(65536),b''):hasher.update(chunk)
        return hasher.hexdigest()
    result['evidence']=[dict(file=p.name,sha256=file_hash(p),bytes=p.stat().st_size)
                        for p in sorted(output.glob('*.stdout'))]
    with (output/'result.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,ensure_ascii=False)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--java',type=Path,required=True)
    parser.add_argument('--tools',type=Path,required=True)
    parser.add_argument('--class',dest='selected',action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:result=analyze(args.apk,args.java,args.tools,args.selected,args.output)
    except OSError:
        print('OUTPUT_UNAVAILABLE_OR_EXISTS');return 2
    print(json.dumps({k:result[k] for k in ('execution_status','verdict','reason_code')}))
    return 0 if result['execution_status']=='completed' else 2


if __name__=='__main__':raise SystemExit(main())
