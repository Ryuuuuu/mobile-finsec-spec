"""Final-only history; live events are a separate run-scoped stream."""
import json
import os
from pathlib import Path
import sqlite3

from .contracts import ContractError, LIMITATIONS, TERMINAL, digest


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def validate_final(result, *, root=None, snapshot=None):
    from .p2_adapter import validate_reference as validate_p2
    from .p3_adapter import validate_reference as validate_p3
    if (result.get('schema_version') != '1.0' or result.get('synthetic') is not True
            or result.get('finalized') is not True or result.get('finalization_version') != '1.0'):
        raise ContractError('FINAL_SCHEMA_INVALID')
    if result.get('execution_status') not in {'completed', 'failed', 'cancelled'}:
        raise ContractError('FINAL_STATUS_INVALID')
    if root is not None:
        record_path = Path(root) / 'run.json'
        if record_path.is_symlink():
            raise ContractError('RUN_SNAPSHOT_SYMLINK')
        record = json.loads(record_path.read_text())
        if (record['run_id'] != result['run_id'] or record['session_id'] != result['session_id']
                or digest(record['plan']) != record['config_hash']
                or result['selected_item_ids'] != [item['item_id'] for item in record['plan']['items']]
                or snapshot is not None and record['contract_snapshot'] != snapshot):
            raise ContractError('FINAL_RUN_SNAPSHOT_MISMATCH')
        snapshot = record['contract_snapshot']
    rows = result['items']
    if (not rows or len(rows) > 10 or [r['item_id'] for r in rows] != result['selected_item_ids']
            or len({r['item_id'] for r in rows}) != len(rows)):
        raise ContractError('FINAL_SELECTION_MISMATCH')
    if result['cleanup_status'] not in {'completed', 'failed', 'unknown'}:
        raise ContractError('FINAL_CLEANUP_INVALID')
    if (result['cleanup_status'] != 'completed' and result['recovery_required'] is not True
            or result['cleanup']['status'] != result['cleanup_status']):
        raise ContractError('FINAL_CLEANUP_INVALID')
    counts = {v: 0 for v in ('pass', 'fail', 'inconclusive')}
    attempts = set()
    bundles = set()
    for row in rows:
        if (row['run_id'] != result['run_id'] or row['session_id'] != result['session_id']
                or row['execution_status'] not in TERMINAL or row['verdict'] not in counts
                or not isinstance(row.get('reason_code'), str) or not row['reason_code'].strip()
                or not isinstance(row.get('reason'), str) or not row['reason'].strip()
                or row.get('synthetic') is not True or row.get('schema_version') != '1.0'
                or row.get('check_id') != 'CHK-07'
                or row.get('verdict_label') != {'pass': '양호', 'fail': '취약', 'inconclusive': '판단 불가능'}[row['verdict']]):
            raise ContractError('FINAL_ROW_INVALID')
        counts[row['verdict']] += 1
        report = row.get('p3')
        if report:
            if row['attempt_id'] in attempts or report['bundle'] in bundles:
                raise ContractError('FINAL_DUPLICATE_ATTEMPT')
            attempts.add(row['attempt_id'])
            bundles.add(report['bundle'])
            if root is not None:
                path = Path(report['bundle'])
                if (path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve())
                        or path.resolve() != (Path(root) / row['item_id']).resolve()):
                    raise ContractError('EVIDENCE_OUTSIDE_RUN')
            raw = validate_p3(report, expected_snapshot=snapshot)
            if (report['run_id'] != result['run_id'] or report['session_id'] != result['session_id']
                    or report['attempt_id'] != row['attempt_id'] or raw['verdict'] != row['verdict']
                    or report['evidence_refs'] != row['evidence_refs']
                    or row['limitations'] != list(dict.fromkeys([*LIMITATIONS, *raw['limitations']]))
                    or any(row[key] != raw[key] for key in ('reason', 'reason_code', 'tested_scope',
                                                           'execution_status', 'cleanup_status'))):
                raise ContractError('FINAL_P3_MISMATCH')
        elif (row['verdict'] != 'inconclusive' or row['evidence_refs']
              or row['execution_status'] == 'completed'):
            raise ContractError('RESULT_INSUFFICIENT_EVIDENCE')
    if counts != result['verdict_counts']:
        raise ContractError('FINAL_COUNTS_MISMATCH')
    if result['execution_status'] == 'completed' and (
            any(row['execution_status'] != 'completed' for row in rows)
            or result['cleanup_status'] != 'completed' or result['recovery_required']
            or result.get('p2') is None):
        raise ContractError('FINAL_COMPLETION_INVALID')
    if result.get('p2'):
        report = result['p2']
        if report['run_id'] != result['run_id'] or report['session_id'] != result['session_id']:
            raise ContractError('FINAL_P2_MISMATCH')
        if root is not None and not Path(report['db']).resolve().is_relative_to(Path(root).resolve()):
            raise ContractError('PACKETS_OUTSIDE_RUN')
        validate_p2(report)
    return result


class History:
    def __init__(self, path):
        self.path = Path(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS history (run_id TEXT PRIMARY KEY, path TEXT NOT NULL, digest TEXT NOT NULL)')

    def finalize(self, result, output, snapshot):
        validate_final(result, root=output, snapshot=snapshot)
        path = Path(output) / 'final.json'
        if path.exists():
            if json.loads(path.read_text()) != result:
                raise ContractError('IMMUTABLE_FINAL_CONFLICT')
        else:
            atomic_json(path, result)
        with sqlite3.connect(self.path) as db:
            existing = db.execute('SELECT digest FROM history WHERE run_id=?', (result['run_id'],)).fetchone()
            if existing and existing[0] != digest(result):
                raise ContractError('IMMUTABLE_HISTORY_CONFLICT')
            db.execute('INSERT OR IGNORE INTO history VALUES (?, ?, ?)', (result['run_id'], str(path), digest(result)))

    def list(self):
        with sqlite3.connect(self.path) as db:
            records = db.execute('SELECT run_id,path,digest FROM history ORDER BY rowid DESC').fetchall()
        values = []
        for run_id, path, expected in records:
            result = json.loads(Path(path).read_text())
            if result['run_id'] != run_id or digest(result) != expected:
                raise ContractError('FINAL_INTEGRITY_ERROR')
            record = json.loads((Path(path).parent / 'run.json').read_text())
            validate_final(result, root=Path(path).parent, snapshot=record['contract_snapshot'])
            values.append(result)
        return values
