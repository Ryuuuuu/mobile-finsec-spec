"""Offline preparation gate. Declarations do not attest devices or authorize execution."""

GATES = ('authorization_current', 'qa_app_build_matched', 'scope_oracle_defined',
         'baseline_state_evidence_reviewed', 'tampered_state_evidence_reviewed',
         'baseline_service_evidence_reviewed', 'causal_oracle_defined',
         'comparison_confounders_reviewed', 'private_evidence_store_ready',
         'lease_and_recovery_reviewed', 'settings_baseline_reviewed')
TRANSPORTS = ('not_checked', 'device', 'offline', 'unauthorized', 'disconnected', 'error')


def assess_readiness(plan):
    if not isinstance(plan, dict) or set(plan) != {'contract', 'synthetic', 'gates', 'transport', 'cleanup'}:
        raise ValueError('INVALID_PLAN')
    if plan['contract'] != 'p3.resume.v1' or type(plan['synthetic']) is not bool:
        raise ValueError('INVALID_CONTRACT')
    gates = plan['gates']
    if not isinstance(gates, dict) or set(gates) != set(GATES) or any(type(v) is not bool for v in gates.values()):
        raise ValueError('INVALID_GATES')
    transport = plan['transport']
    if not isinstance(transport, dict) or set(transport) != {'baseline', 'test'}:
        raise ValueError('INVALID_TRANSPORT')
    if any(v not in TRANSPORTS for v in transport.values()) or plan['cleanup'] not in ('verified', 'unknown', 'failed'):
        raise ValueError('INVALID_STATE')
    blockers = [key for key in GATES if not gates[key]]
    blockers += [phase + '_transport_' + state for phase, state in transport.items() if state != 'device']
    if plan['cleanup'] != 'verified':
        blockers.append('recovery_review_required')
    return {'contract': 'p3.resume.v1', 'synthetic': plan['synthetic'], 'verdict': 'inconclusive',
            'device_execution': 'not_run', 'auto_resume': False,
            'readiness': 'blocked' if blockers else 'ready_for_manual_review',
            'blockers': blockers,
            'limitations': ['Declarations are not attestation or service observations.',
                            'Transport state may be stale; recheck under the device lease.',
                            'This gate does not grant approval or execute device commands.']}


def empty_plan():
    return {'contract': 'p3.resume.v1', 'synthetic': True,
            'gates': {key: False for key in GATES},
            'transport': {'baseline': 'not_checked', 'test': 'not_checked'}, 'cleanup': 'unknown'}
