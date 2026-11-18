"""Content-agnostic skill loading for structural tests; no assessment execution."""
from copy import deepcopy
import hashlib
from pathlib import Path
import re


def load_skills(root, item_id, platform=None):
    if not isinstance(item_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',item_id):
        raise ValueError('INVALID_ITEM')
    if platform not in (None,'aos','ios'):
        raise ValueError('INVALID_PLATFORM')
    root=Path(root).resolve(strict=True)
    skills=[]
    for role in ('common',) + ((platform,) if platform else ()):
        path=root/item_id/role/'SKILL.md'
        if any(p.is_symlink() for p in (path,path.parent,path.parent.parent)):
            raise ValueError('SYMLINK_SKILL')
        resolved=path.resolve(strict=True)
        if not resolved.is_relative_to(root):raise ValueError('SKILL_OUTSIDE_ROOT')
        with resolved.open('rb') as stream:data=stream.read(65537)
        if len(data)>65536:raise ValueError('SKILL_TOO_LARGE')
        text=data.decode('utf-8')
        if not text.strip():raise ValueError('EMPTY_SKILL')
        skills.append(dict(role=role,sha256=hashlib.sha256(data).hexdigest(),content=text))
    return dict(contract='opaque-skills.v1',item_id=item_id,platform=platform,skills=skills)


def provider_context(bundle):
    # Pass a detached snapshot; do not parse tools, verdicts, or instructions.
    if not isinstance(bundle,dict) or bundle.get('contract')!='opaque-skills.v1':
        raise ValueError('INVALID_SKILL_BUNDLE')
    return {'skill_snapshot':deepcopy(bundle)}
