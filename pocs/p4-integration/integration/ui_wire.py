"""Bounded JSON boundary for mock UI integration; not a network server."""
import json

LIMIT = 256 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_KEY')
        result[key] = value
    return result


class UIWire:
    def __init__(self, bridge):
        self.bridge = bridge

    def exchange(self, raw):
        # Call only on the API's asyncio thread. Mutation may precede a lost reply;
        # callers must reuse the command ID, never silently create a new one.
        try:
            if not isinstance(raw, bytes) or len(raw) > LIMIT:
                raise ValueError('LIMIT')
            msg = json.loads(raw, object_pairs_hook=_object)
            if not isinstance(msg, dict) or set(msg) != {'contract', 'project_id', 'request_generation', 'operation', 'arguments'}:
                raise ValueError('SCHEMA')
            if msg['contract'] != 'mock-ui-request.v1' or msg['project_id'] != self.bridge.project_id:
                raise ValueError('SCOPE_OR_VERSION')
            gen = msg['request_generation']
            if type(gen) is not int or not 0 <= gen <= 2**53-1:
                raise ValueError('GENERATION')
            op, args = msg['operation'], msg['arguments']
            fields = {'recordings': set(), 'recording': {'ref'}, 'inspect': {'request'}, 'submit': {'request'},
                      'progress': {'execution_id', 'cursor'}, 'cancel': {'execution_id'},
                      'history': set(), 'result': {'run_id'}}
            if not isinstance(op, str) or op not in fields or not isinstance(args, dict) or set(args) != fields[op]:
                raise ValueError('OPERATION')
            for key in ('ref', 'execution_id', 'run_id'):
                if key in args and (not isinstance(args[key], str) or not 1 <= len(args[key]) <= 128):
                    raise ValueError('IDENTIFIER')
            if op in ('inspect', 'submit'):
                data = getattr(self.bridge.api, op)(args['request'])
                reply = self.bridge.envelope(gen, operation=op, data=data)
            elif op == 'cancel':
                reply = self.bridge.envelope(gen, operation=op, data=self.bridge.api.cancel(args['execution_id']))
            else:
                reply = getattr(self.bridge, op)(generation=gen, **args)
            encoded = json.dumps(reply, allow_nan=False).encode('utf-8')
            if len(encoded) > LIMIT:
                return b'{"error":"RESPONSE_LIMIT","outcome":"unknown"}'
            return encoded
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            return b'{"error":"INVALID_REQUEST_OR_RESPONSE","outcome":"unknown"}'
        except (OSError, RuntimeError):
            return b'{"error":"SERVICE_UNAVAILABLE","outcome":"unknown"}'
