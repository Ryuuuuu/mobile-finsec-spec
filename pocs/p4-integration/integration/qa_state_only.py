"""Fixed instrumentation of a disposable local QA app, not an arbitrary app adapter."""
import subprocess

COMPONENT = 'dev.finsec.qa.stateonly/dev.finsec.qa.stateonly.StateProbe'


def run_probe(adb, device):
    if not isinstance(device, str) or not device or device.startswith('-') or any(c.isspace() for c in device):
        raise ValueError('INVALID_DEVICE')
    try:
        result = subprocess.run([str(adb), '-s', device, 'shell', 'am', 'instrument',
                                 '-w', '-r', COMPONENT], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        return {'contract':'state-only.v1','status':'outcome_unknown','states':[],
                'cleanup':'unverified','retry_allowed':False}
    except OSError:
        return {'contract':'state-only.v1','status':'transport_error','states':[],
                'cleanup':'unverified','retry_allowed':False}
    expected = {b'INSTRUMENTATION_RESULT: qa_contract=state-only.v1',
                b'INSTRUMENTATION_RESULT: qa_states=QA_READY>QA_SENT',
                b'INSTRUMENTATION_CODE: -1'}
    lines = result.stdout.splitlines()
    valid = result.returncode == 0 and len(lines) == 3 and set(lines) == expected
    return {'contract':'state-only.v1','status':'completed' if valid else 'unverified',
            'states':['QA_READY','QA_SENT'] if valid else [],
            'cleanup':'activity_finish_reported' if valid else 'unverified',
            'retry_allowed':False}
