"""Public synthetic HTTP fixture. Loopback only; no real credentials or devices."""
import argparse
import asyncio
import json
import urllib.request


async def upstream(port):
    async def handle(reader, writer):
        try:
            data = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            request_line = data.split(b'\r\n', 1)[0].decode('ascii')
            size = next((int(line.split(b':', 1)[1]) for line in data.split(b'\r\n') if line.lower().startswith(b'content-length:')), 0)
            if not 0 <= size <= 1048576:
                return
            await asyncio.wait_for(reader.readexactly(size), 2)
            body = json.dumps({'fixture': 'synthetic-only', 'request': request_line}).encode()
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(handle, '127.0.0.1', port, limit=16384)
    print(json.dumps({'schema_version': 1, 'fixture': 'synthetic-only', 'port': server.sockets[0].getsockname()[1]}), flush=True)
    async with server:
        await server.serve_forever()


def client(port, count):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    delivered = []
    for index in range(count):
        with opener.open(f'http://127.0.0.1:{port}/synthetic/{index}', timeout=3) as response:
            body = json.loads(response.read())
            if response.status != 200 or body.get('request') != f'GET /synthetic/{index} HTTP/1.1':
                raise RuntimeError('unexpected_fixture_response')
            delivered.append(index)
    print(json.dumps({'schema_version': 1, 'delivered': len(delivered), 'ids': delivered}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('upstream', 'client'))
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--count', type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.count <= 1000:
        parser.error('port=1..65535 and count=1..1000 required')
    try:
        if args.action == 'upstream':
            asyncio.run(upstream(args.port))
        else:
            client(args.port, args.count)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
