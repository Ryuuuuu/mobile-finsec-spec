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
                selected=[],
                coverage=dict(dex_inventory='not_run',dex_defined='not_run',selected_smali='not_run',
                    whole_application='not_assessed',native=dict(status='not_analyzed',entry_count=None),
                    webview=dict(status='not_analyzed',reference_signal='unknown'),
                    resources=dict(status='not_analyzed',web_asset_count=None)),
                limits=dict(apk_bytes=MAX_APK,tool_timeout_seconds=30,tool_output_bytes=4*1024*1024,total_seconds=120,max_dex_files=16),
                limitations=['Actual DEX evidence only; no security verdict or semantic readability scoring.',
                    'No signature verification, native/resource analysis, runtime or whole-app coverage.',
                    'Direct Java timeout management is not a hostile-parser OS sandbox.'])
    deadline=time.monotonic()+120
    def invoke(command,label):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise AnalysisError('ANALYSIS_TIMEOUT')
        return run_tool(command,output,label,timeout=min(30,remaining))
    stage='preflight'
    try:
        if (not selected or len(selected)>20 or len(set(selected))!=len(selected)
                or any(not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*',s) for s in selected)):
            raise AnalysisError('INVALID_CLASS_SELECTION')
        props=bounded(Path(tools)/'source.properties',16384).decode('utf-8')
        if 'Pkg.Revision=19.0' not in props.splitlines():raise AnalysisError('UNSUPPORTED_TOOL_VERSION')
        jar=Path(tools)/'lib/apkanalyzer-classpath.jar'
        result['tool']=dict(package='Android SDK Command-line Tools',revision='19.0',
            launcher_jar_sha256=digest(bounded(jar,MAX_APK)))
        stage='inventory'
        info,entries=inventory(apk)
        result['inventory']=info
        result['coverage']['native'].update(entry_count=info['native_entries'],presence_basis='ZIP paths only, not ELF validation')
        result['coverage']['resources']['web_asset_count']=sum(n.endswith(('.js','.html','.htm')) for n in entries)
        result['coverage']['nonstandard_dex_entries']=[n for n in entries if n.endswith('.dex') and not re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex',n)]
        raw=bounded(apk,MAX_APK)
        if digest(raw)!=info['artifact_sha256']:raise AnalysisError('ARTIFACT_CHANGED')
        snapshot=output/'input.apk';snapshot.write_bytes(raw)
        prefix=[java,'-Xmx256m','-Dcom.android.sdklib.toolsdir='+str(Path(tools).resolve()),'-cp',jar,
                'com.android.tools.apk.analyzer.ApkAnalyzerCli']
        stage='dex-list'
        dexlist=invoke([*prefix,'dex','list',snapshot],'dex-list')
        dexnames=[line.strip().lstrip('/') for line in dexlist.splitlines() if line.strip()]
        expected=sorted(n for n in entries if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex',n))
        if len(expected)>16:raise AnalysisError('DEX_COUNT_LIMIT')
        if not dexnames or sorted(dexnames)!=expected:raise AnalysisError('DEX_LIST_MISMATCH')
        result['coverage']['dex_inventory']='complete'
        result['coverage']['dex_defined']='partial'
        result['dex_files']=[]
        all_classes=[];all_methods=[];all_fields=[]
        for index,dexname in enumerate(dexnames):
            stage='dex-packages:'+dexname
            text=invoke([*prefix,'dex','packages','--defined-only','--files',dexname,snapshot],f'packages-{index}')
            parsed=parse_packages(text)
            if set(all_classes).intersection(parsed['classes']):raise AnalysisError('DUPLICATE_CLASS_ACROSS_DEX')
            result['dex_files'].append(dict(name=dexname,sha256=digest(entries[dexname]),**parsed))
            all_classes.extend(parsed['classes']);all_methods.extend(parsed['methods']);all_fields.extend(parsed['fields'])
        result['defined']=dict(classes=all_classes,methods=all_methods,fields=all_fields,
            class_count=len(all_classes),method_count=len(all_methods),field_count=len(all_fields),
            short_class_names=sum(len(c.rsplit('.',1)[-1])<=2 for c in all_classes))
        result['coverage']['dex_defined']='complete'
        result['coverage']['webview']['reference_signal']='observed' if any('android.webkit.WebView' in m for m in all_methods+all_fields) else 'not_observed_in_defined_signatures'
        if any(name not in all_classes for name in selected):raise AnalysisError('SELECTED_CLASS_MISSING')
        result['coverage']['selected_smali']='partial'
        for index,name in enumerate(selected):
            stage='smali:'+name
            text=invoke([*prefix,'dex','code','--class',name,snapshot],f'code-{index}')
            summary=smali_summary(text,name)
            summary['dex_file']=next(item['name'] for item in result['dex_files'] if name in item['classes'])
            result['selected'].append(summary)
            if 'Landroid/webkit/WebView;' in text:result['coverage']['webview']['reference_signal']='observed'
        result['coverage']['selected_smali']='complete'
        result.update(execution_status='completed',reason_code='DEX_EVIDENCE_NOT_SECURITY_VERDICT')
    except (OSError,ValueError,TypeError,RuntimeError,zipfile.BadZipFile,NotImplementedError) as exc:
        known_limits={'INPUT_LIMIT','EXPANSION_LIMIT','ENTRY_LIMIT'}
        result['reason_code']=str(exc) if isinstance(exc,AnalysisError) or str(exc) in known_limits else 'INPUT_OR_TOOL_ERROR'
        result['failure_stage']=stage
    result['coverage']['unextracted_selected_classes']=[name for name in (selected or []) if name not in {r['class_name'] for r in result['selected']}]
    def file_hash(path):
        hasher=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(65536),b''):hasher.update(chunk)
        return hasher.hexdigest()
    result['evidence']=[dict(file=p.name,sha256=file_hash(p),bytes=p.stat().st_size)
                        for p in sorted(output.iterdir()) if p.suffix in {'.stdout','.stderr'}]
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
