"""Closed synthetic plans; execution status and security verdict stay separate."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from datetime import datetime, timezone


class ContractError(ValueError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Item:
    item_id: str
    variant: str = 'pass'
    check_id: str = 'CHK-07'
    provider_behavior: str = 'normal'
    tool_fault: str = 'none'
    cleanup_fault: str = 'completed'


@dataclass(frozen=True)
class Plan:
    command_id: str
    items: tuple[Item, ...] = (Item('chk07-pass'),)
    schema_version: str = '1.0'
    synthetic: bool = True
    device_id: str = 'synthetic-device-p4'
    app_id: str = 'dev.finsec.synthetic'
    platform: str = 'aos'
    proxy_on: bool = True
    main_behavior: str = 'normal'
    provider_name: str = 'fake-a'
    cancellation_supported: bool = True
    heartbeat_timeout: float = 0.5
    progress_timeout: float = 0.6
    tool_timeout: float = 5.0
    item_timeout: float = 6.0
    run_timeout: float = 20.0
    cancel_grace: float = 0.1
    cleanup_timeout: float = 3.0

    def snapshot(self):
        data = asdict(self)
        data['items'] = list(data['items'])
        return data

    def validate(self):
        behaviors = {'normal', 'quiet', 'error', 'exit', 'hang', 'heartbeat_lost',
                     'ignores_cancel', 'out_of_scope'}
        if (self.schema_version != '1.0' or self.synthetic is not True
                or self.device_id != 'synthetic-device-p4'
                or self.app_id != 'dev.finsec.synthetic' or self.platform != 'aos'):
            raise ContractError('UNSUPPORTED_SYNTHETIC_TARGET_OR_VERSION')
        if not isinstance(self.command_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', self.command_id):
            raise ContractError('INVALID_COMMAND_ID')
        if not isinstance(self.items, tuple) or not 1 <= len(self.items) <= 10:
            raise ContractError('INVALID_SELECTION')
        if len({i.item_id for i in self.items}) != len(self.items):
            raise ContractError('DUPLICATE_ITEM_ID')
        for item in self.items:
            if (not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', item.item_id)
                    or item.check_id != 'CHK-07' or item.variant not in {'pass', 'fail', 'inconclusive'}
                    or item.provider_behavior not in behaviors
                    or item.tool_fault not in {'none', 'timeout', 'error', 'disconnect'}
                    or item.cleanup_fault not in {'completed', 'failed', 'unknown'}):
                raise ContractError('INVALID_ITEM')
        if self.main_behavior not in behaviors or self.provider_name not in {'fake-a', 'fake-b'}:
            raise ContractError('FAKE_PROVIDER_REQUIRED')
        if type(self.proxy_on) is not bool or type(self.cancellation_supported) is not bool:
            raise ContractError('INVALID_BOOLEAN')
        for key in ('heartbeat_timeout', 'progress_timeout', 'tool_timeout', 'item_timeout',
                    'run_timeout', 'cancel_grace', 'cleanup_timeout'):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0.01 <= value <= 120:
                raise ContractError('INVALID_DEADLINE')
        return self


TERMINAL = {'completed', 'failed', 'timed_out', 'cancelled', 'not_run'}
LIMITATIONS = [
    'Synthetic/fake only; P1, GPUI, real models and real-device integration unverified.',
    'P2 packet correlation is not CHK-07 causal or verdict evidence.',
    'Cooperative gateway is not OS isolation; no automatic recovery or resume.',
]


def empty_result(item, run_id, session_id, code, status='not_run'):
    return dict(schema_version='1.0', synthetic=True, run_id=run_id, session_id=session_id,
                item_id=item.item_id, check_id=item.check_id, attempt_id=None,
                execution_status=status, verdict='inconclusive', verdict_label='판단 불가능',
                reason_code=code, reason=f'Synthetic execution did not establish a verdict: {code}.',
                tested_scope=[], limitations=list(LIMITATIONS), evidence_refs=[], p3=None,
                cleanup_status='completed')
