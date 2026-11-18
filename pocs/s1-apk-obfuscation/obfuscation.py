"""Offline APK inventory and explicitly synthetic CHK-15 evidence evaluator."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

MAX_APK = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_ENTRY = 8 * 1024 * 1024
MARKER = b'CHK15-SYNTHETIC-NOT-INSTALLABLE-v1'
POLICY = 'synthetic-two-dimension-v1'
DIMENSIONS = {'identifiers', 'logic_readability'}
LIMITATIONS = [
    'No DEX decompilation, signature verification or semantic analysis.',
    'Synthetic review records are not independent analysis attestations.',
    'No whole-app, real-app or official compliance conclusion.',
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bounded(path, limit):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('SYMLINK_INPUT')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('INPUT_LIMIT')
    return data


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('DUPLICATE_KEY')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('NONFINITE_JSON')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def inventory(path):
    raw = bounded(path, MAX_APK)
    entries = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > 1024:
            raise ValueError('ENTRY_LIMIT')
        total = 0
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            if (info.orig_filename != name or not name or name in entries or name.startswith('/') or '\\' in name
                    or ':' in name or '..' in parts or info.flag_bits & 1
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('UNSAFE_ARCHIVE')
            total += info.file_size
            if (info.file_size > MAX_ENTRY or total > MAX_EXPANDED
                    or info.file_size > 200 * max(info.compress_size, 1)):
                raise ValueError('EXPANSION_LIMIT')
            entries[name] = archive.read(info)  # bounded above; CRC checked, never extracted
    if 'AndroidManifest.xml' not in entries:
        raise ValueError('MANIFEST_MISSING')
    result = dict(artifact_sha256=digest(raw), bytes=len(raw), entries=len(entries),
                  dex_entries=sum(bool(re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', n)) for n in entries),
                  native_entries=sum(n.startswith('lib/') and n.endswith('.so') for n in entries),
                  resource_entries=sum(n.startswith('res/') for n in entries))
    return result, entries


def base(info, synthetic):
    return dict(schema_version='1.0', check_id='CHK-15', synthetic=synthetic,
                execution_status='completed', verdict='inconclusive',
                reason_code='INVENTORY_NOT_OBFUSCATION_EVIDENCE', inventory=info,
                scopes=[], limitations=list(LIMITATIONS))


def evaluate(info, entries, review):
    result = base(info, True)
    if entries.get('assets/CHK15-SYNTHETIC') != MARKER:
        raise ValueError('SYNTHETIC_FIXTURE_REQUIRED')
    if not isinstance(review, dict) or review.get('schema_version') != '1.0' or review.get('synthetic') is not True:
        raise ValueError('REVIEW_SCHEMA')
    if review.get('artifact_sha256') != info['artifact_sha256']:
        result['reason_code'] = 'ARTIFACT_MISMATCH'
        return result
    scopes = review.get('selected_scopes')
    if (not isinstance(scopes, list) or not 1 <= len(scopes) <= 20
            or any(not isinstance(s, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', s) for s in scopes)
            or len(set(scopes)) != len(scopes)):
        result['reason_code'] = 'SCOPE_UNDEFINED'
        return result
    if review.get('policy') != POLICY:
        result['reason_code'] = 'POLICY_UNDEFINED'
        return result
    refs = review.get('evidence')
    if not isinstance(refs, list) or len(refs) > 80:
        raise ValueError('EVIDENCE_SCHEMA')
    for scope in scopes:
        found = {}
        reasons = []
        used = set()
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError('REFERENCE_SCHEMA')
            if ref.get('scope') != scope:
                continue
            name = ref.get('entry')
            if not isinstance(name, str) or name in used or name not in entries:
                reasons.append('MISSING_OR_REUSED_EVIDENCE')
                continue
            used.add(name)
            data = entries[name]
            if len(data) > 16384 or digest(data) != ref.get('sha256'):
                reasons.append('EVIDENCE_HASH_OR_SIZE')
                continue
            try:
                observation = decode(data)
            except (ValueError, UnicodeError):
                reasons.append('INVALID_EVIDENCE')
                continue
            if (not isinstance(observation, dict) or observation.get('synthetic') is not True
                    or observation.get('scope') != scope
                    or observation.get('tool') != 'synthetic-review/1'
                    or observation.get('status') != 'completed'):
                reasons.append('UNVERIFIED_OBSERVATION')
                continue
            dim = observation.get('dimension')
            value = observation.get('finding')
            if dim not in DIMENSIONS or value not in ('supports', 'violates') or dim in found:
                reasons.append('UNKNOWN_OR_CONFLICTING_DIMENSION')
                continue
            found[dim] = value
        verdict = 'inconclusive'
        if not reasons and set(found) == DIMENSIONS:
            if set(found.values()) == {'supports'}:
                verdict = 'pass'
            elif set(found.values()) == {'violates'}:
                verdict = 'fail'
        result['scopes'].append(dict(scope=scope, verdict=verdict,
            reason_codes=reasons or (['TWO_DIMENSIONS_AGREE'] if verdict != 'inconclusive' else ['INSUFFICIENT_OR_MIXED_EVIDENCE'])))
    verdicts = [s['verdict'] for s in result['scopes']]
    result['verdict'] = 'fail' if 'fail' in verdicts else 'pass' if all(v == 'pass' for v in verdicts) else 'inconclusive'
    result['reason_code'] = 'SYNTHETIC_POLICY_RESULT'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'evaluate'))
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        print('OUTPUT_EXISTS')
        return 2
    try:
        info, entries = inventory(args.apk)
        result = base(info, False) if args.mode == 'inspect' else evaluate(
            info, entries, decode(bounded(args.review, 65536)))
        code = 0
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        result = dict(schema_version='1.0', check_id='CHK-15', synthetic=args.mode=='evaluate',
                      execution_status='failed', verdict='inconclusive', reason_code='INPUT_REJECTED',
                      scopes=[], limitations=list(LIMITATIONS))
        code = 2
    try:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except OSError:
        print('OUTPUT_NOT_SAVED')
        return 2
    print(json.dumps({'execution_status':result['execution_status'],'verdict':result['verdict']}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
