"""Synthetic-only child process. Private inherited pipes, no network listener."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from .start_api import StartAPI
from .structure_supervisor import StructureSupervisor
from .ui_bridge import UIBridge
from .ui_wire import UIWire, LIMIT


async def serve(root):
    # Keep fixture skills separate from user-authored inspection skills.
    skills = root / 'mock-skills'
    path = skills / 'mock-item' / 'common' / 'SKILL.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text('OPAQUE MOCK FIXTURE', encoding='utf-8')
    platform = skills / 'mock-item' / 'aos' / 'SKILL.md'
    platform.parent.mkdir(parents=True, exist_ok=True)
    if not platform.exists():
        platform.write_text('OPAQUE MOCK FIXTURE', encoding='utf-8')
    inventory = {'revision': 1, 'devices': {'synthetic-device-p4': {
        'platform': 'aos', 'connection': 'connected', 'authorized': True,
        'capabilities': {'mock_input': True}}}}
    catalog = {'mock-item': {'platforms': ['aos'], 'common_skill': True,
        'platform_skills': ['aos'], 'requires': ['mock_input']}}
    api = StartAPI(StructureSupervisor(root / 'runs', skills), inventory, catalog)
    wire = UIWire(UIBridge('synthetic-stdio', api))
    def write(payload):
        sys.stdout.buffer.write(payload + b'\n')
        sys.stdout.buffer.flush()
    write(json.dumps({'contract': 'mock-stdio.v1', 'status': 'ready',
                      'synthetic': True}).encode())
    try:
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline, LIMIT + 2)
            if not raw:
                break
            if len(raw) > LIMIT + 1 or not raw.endswith(b'\n'):
                write(b'{"error":"INVALID_FRAME","outcome":"unknown"}')
                break  # Never reinterpret the remainder as another request.
            write(wire.exchange(raw[:-1]))
    finally:
        jobs = [job for job in api.jobs.values() if not job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            _, pending = await asyncio.wait(jobs, timeout=1)
            if pending:
                # The parent still owns the process deadline. Do not claim cleanup.
                write(b'{"contract":"mock-stdio.v1","status":"recovery_required"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mock-root', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.mock_root))


if __name__ == '__main__':
    main()
