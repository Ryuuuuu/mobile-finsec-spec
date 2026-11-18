"""Disposable synthetic HTTP child; bootstrap secret goes only to inherited stdout."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from .mock_stdio import create_mock_api
from .loopback_api import LoopbackAPI
from .ui_bridge import UIBridge
from .ui_wire import UIWire


async def serve(root):
    api = create_mock_api(root)
    server = LoopbackAPI(UIWire(UIBridge('synthetic-http', api)))
    await server.start()
    descriptor = dict(contract='mock-http-child.v1', synthetic=True, host='127.0.0.1',
                      port=server.port, token=server.token, project_id='synthetic-http')
    sys.stdout.buffer.write(json.dumps(descriptor).encode() + b'\n');sys.stdout.buffer.flush()
    try:
        # Only EOF is the shutdown signal; never interpret stdin as commands.
        while await asyncio.to_thread(sys.stdin.buffer.read, 1):
            pass
    finally:
        await server.close()
        jobs = [job for job in api.jobs.values() if not job.done()]
        for job in jobs: job.cancel()
        pending = set()
        if jobs: _, pending = await asyncio.wait(jobs, timeout=1)
    return 3 if pending or api.supervisor.lease.inspect()['lifecycle'] != 'free' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mock-root', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(serve(args.mock_root)))
