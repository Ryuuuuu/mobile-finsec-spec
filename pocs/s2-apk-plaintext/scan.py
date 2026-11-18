"""Bounded exact-byte scan for PUBLIC SYNTHETIC markers, not secret discovery."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile
import zlib

# Shared finite ZIP budgets; no SDK, subprocess, device or network invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 's1-apk-obfuscation'))
from apk_budget import Limits, ResourceError, CHUNK, snapshot_inventory, time_guard, storage_guard

MARKERS = {'demo_token': b'QA_PLAINTEXT_DEMO_TOKEN_001', 'qa_status': b'QA_INVALID'}

PATTERNS = {(key, encoding): value.decode('ascii').encode(encoding)
            for key, value in MARKERS.items()
            for encoding in ('utf-8', 'utf-16le', 'utf-16be')}
SAFE_REASONS = {'MATCH_LIMIT', 'ANALYSIS_TIMEOUT', 'INPUT_LIMIT', 'UNSAFE_ARCHIVE',
                'EXPANSION_LIMIT', 'DISK_BUDGET_LIMIT', 'DISK_FREE_LIMIT',
                'SYMLINK_INPUT', 'ARTIFACT_CHANGED_DURING_COPY', 'ENTRY_LIMIT',
                'CENTRAL_DIRECTORY_LIMIT', 'INVALID_ZIP_DIRECTORY',
                'UNSUPPORTED_MULTIDISK_ZIP', 'UNSUPPORTED_ZIP64',
                'ENTRY_SIZE_MISMATCH', 'MANIFEST_MISSING'}


def scan(apk, output, limits=None, max_matches=100):
    limits = (limits or Limits()).validate()
    if type(max_matches) is not int or not 1 <= max_matches <= 1000:
        raise ValueError('INVALID_MATCH_LIMIT')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + limits.total_seconds
    result = dict(schema_version='1.1', check_id='CHK-11-mobile-extension',
                  scope='apk_static_synthetic_literal', verdict='inconclusive',
                  representations=list(('utf-8', 'utf-16le', 'utf-16be')),
                  semantic_extraction='not_run',
                  commandline_observation='not_run', execution_status='failed',
                  literal_observation='unknown', coverage='not_started',
                  artifact=None, completed_entries=0, scanned_bytes=0, matches=[],
                  limits=limits.snapshot(), max_matches=max_matches,
                  catalog={k: dict(length=len(v), sha256=hashlib.sha256(v).hexdigest())
                           for k, v in MARKERS.items()})
    stage = 'inventory'
    try:
        info, entries = snapshot_inventory(apk, output, limits, deadline)
        result['artifact'] = info
        result['coverage'] = 'partial'
        stage = 'literal_scan'
        overlap = max(map(len, PATTERNS.values())) - 1
        with zipfile.ZipFile(output / 'input.apk') as archive:
            for name, entry in entries.items():
                tail = b''
                consumed = 0
                with archive.open(name) as stream:
                    while True:
                        time_guard(deadline)
                        chunk = stream.read(CHUNK)
                        if not chunk:
                            break
                        data = tail + chunk
                        base = consumed - len(tail)
                        found = []
                        for (marker_id, encoding), marker in PATTERNS.items():
                            start = 0
                            while True:
                                pos = data.find(marker, start)
                                if pos < 0:
                                    break
                                offset = base + pos
                                if offset + len(marker) > consumed:
                                    found.append((offset, marker_id, encoding, len(marker)))
                                    if len(found) + len(result['matches']) > max_matches:
                                        # Bounded temporary list too; no unbounded repeated matches.
                                        raise ResourceError('MATCH_LIMIT')
                                start = pos + 1
                        for offset, marker_id, encoding, length in sorted(found):
                            result['matches'].append(dict(marker_id=marker_id, representation=encoding,
                                entry_id=hashlib.sha256(name.encode('utf-8')).hexdigest(),
                                offset=offset, length=length, entry_sha256=entry['sha256']))
                        consumed += len(chunk)
                        result['scanned_bytes'] += len(chunk)
                        tail = data[-overlap:]
                result['completed_entries'] += 1
        result.update(execution_status='completed', coverage='complete', reason_code='SCAN_COMPLETE')
    except (ResourceError, OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as exc:
        # Never serialize external exception text, input paths or entry payloads.
        reason = str(exc) if isinstance(exc, ResourceError) and str(exc) in SAFE_REASONS else 'INPUT_OR_SCAN_ERROR'
        result.update(reason_code=reason, failed_stage=stage)
    if result['matches']:
        result['literal_observation'] = 'found'
    elif result['execution_status'] == 'completed':
        result['literal_observation'] = 'not_observed'
    payload = json.dumps(result, indent=2, ensure_ascii=True).encode('utf-8')
    storage_guard(output, limits, len(payload), reserve=0)
    with (output / 'result.json.tmp').open('xb') as stream:
        stream.write(payload)
    (output / 'result.json.tmp').replace(output / 'result.json')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('output', type=Path, help='new private directory; retains input snapshot')
    parser.add_argument('--apk-mib', type=int, default=32)
    parser.add_argument('--disk-mib', type=int, default=128)
    parser.add_argument('--max-matches', type=int, default=100)
    args = parser.parse_args()
    try:
        result = scan(args.apk, args.output,
                      Limits(apk_mib=args.apk_mib, disk_mib=args.disk_mib), args.max_matches)
    except (OSError, ValueError):
        print('INVALID_CONFIGURATION_OR_OUTPUT; no successful result')
        return 2
    print(json.dumps({k: result[k] for k in ('execution_status', 'literal_observation', 'verdict', 'reason_code')}))
    return 0 if result['execution_status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
