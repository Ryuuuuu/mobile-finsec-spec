"""Check this authored QA pair's extraction evidence, not security compliance."""
import argparse
import json
from pathlib import Path
import re
from obfuscation import digest


def compare(pair,plain,renamed):
    results=[]
    for variant,folder in (('plain',plain),('renamed',renamed)):
        result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
        if result['execution_status']!='completed' or result['verdict']!='inconclusive':
            raise ValueError('EXTRACTION_NOT_ACCEPTED')
        if result['inventory']['artifact_sha256']!=digest((pair/(variant+'.apk')).read_bytes()):
            raise ValueError('WRONG_ARTIFACT')
        for ref in result['evidence']:
            path=folder/ref['file']
            if path.parent!=folder or digest(path.read_bytes())!=ref['sha256']:
                raise ValueError('EVIDENCE_MISMATCH')
        results.append(result)
    mapping=(pair/'mapping.txt').read_text(encoding='utf-8')
    match=re.search(r'^dev\.finsec\.s1\.ImportantLogic -> ([\w.]+):$',mapping,re.M)
    if not match:raise ValueError('QA_MAPPING_MISSING')
    target=match.group(1)
    a,b=results
    if ('dev.finsec.s1.ImportantLogic' not in a['defined']['classes'] or target not in b['defined']['classes']
            or 'dev.finsec.s1.ImportantLogic' in b['defined']['classes']):raise ValueError('CLASS_RENAME_NOT_OBSERVED')
    before=(plain/'code-0.stdout').read_text(encoding='utf-8')
    after=(renamed/'code-0.stdout').read_text(encoding='utf-8')
    if 'classifyDemoUnits(I)' not in before or 'classifyDemoUnits(I)' in after:
        raise ValueError('METHOD_RENAME_NOT_OBSERVED')
    if not all(token in text for text in (before,after) for token in ('QA_INVALID','QA_LIMIT','QA_ACCEPTED')):
        raise ValueError('QA_STRINGS_NOT_OBSERVED')
    if not all(r['selected'][0]['conditional_instructions']==2 for r in results):
        raise ValueError('QA_BRANCHES_NOT_OBSERVED')
    return dict(check='authored-qa-pair-only',class_renaming_observed=True,method_renaming_observed=True,
                qa_strings_visible_in_both=True,conditional_instructions_each=2,
                selected_method_bodies=[r['selected'][0]['method_bodies'] for r in results],
                security_verdict='inconclusive',semantic_equivalence_proved=False,
                note='Known-source fixture evidence; no general readability or protection conclusion.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pair','plain','renamed','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();result=compare(args.pair,args.plain,args.renamed)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print('Controlled QA comparison completed; security verdict inconclusive.')
