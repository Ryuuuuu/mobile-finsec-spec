"""Pure, bounded matching of declarative metadata to predefined synthetic QA events.

No skill body, model, I/O, action generation, or executable expression is accepted.
"""
from dataclasses import asdict, dataclass
from .observation_poc import Plan, STATES, PHASES, digest, identifier

EVENTS = frozenset(('QA_ENTER', 'QA_SUBMIT'))


@dataclass(frozen=True)
class TimingRule:
    check_id: str
    condition_kind: str
    condition_value: str
    phase: str
    required_evidence: tuple[str, ...] = ('qa_state',)
    schema_version: str = 'qa-observation-timing.v1'


@dataclass(frozen=True)
class QAEvent:
    event_id: str
    recording_id: str
    route_version: str
    route_hash: str
    occurrence: int
    step_id: str
    phase: str
    state: str
    event: str


def match_timing(routes, applicability, rules, events):
    if type(rules) is not tuple or not 1 <= len(rules) <= 10 or type(events) is not tuple or len(events)>200:
        raise ValueError('MATCH_INPUT_LIMIT_OR_MUTABILITY')
    for rule in rules:
        if type(rule) is not TimingRule: raise ValueError('INVALID_TIMING_RULE')
        identifier(rule.check_id)
        if (rule.schema_version!='qa-observation-timing.v1' or rule.phase not in PHASES
                or rule.required_evidence!=('qa_state',) or rule.condition_kind not in ('state','event')
                or rule.condition_value not in (STATES if rule.condition_kind=='state' else EVENTS)):
            raise ValueError('UNSUPPORTED_TIMING_RULE')
    selected=tuple(r.check_id for r in rules)
    plan=Plan(routes,(),schema_version=2,selected_check_ids=selected,applicability=applicability)
    plan.validate(plan.content_hash)  # Complete matrix, distinct selections; no storage or execution.
    by_route={(r.recording_id,r.occurrence):r for r in routes}
    seen=set()
    for event in events:
        if type(event) is not QAEvent or type(event.occurrence) is not int:raise ValueError('INVALID_QA_EVENT')
        identifier(event.event_id)
        route=by_route.get((event.recording_id,event.occurrence))
        if (route is None or event.route_version!=route.version or event.route_hash!=route.content_hash
                or event.step_id not in route.steps or event.phase not in PHASES
                or event.state not in STATES or event.event not in EVENTS):raise ValueError('QA_EVENT_SCOPE_MISMATCH')
        identity=(event.recording_id,event.occurrence,event.event_id)
        if identity in seen:raise ValueError('DUPLICATE_QA_EVENT')
        seen.add(identity)
    metadata_hash=digest([asdict(r) for r in rules])
    rows=[]
    for cell in applicability:
        rule=next(r for r in rules if r.check_id==cell.check_id)
        route=by_route[cell.recording_id,cell.occurrence]
        candidates=[e for e in events if (e.recording_id,e.occurrence)==(cell.recording_id,cell.occurrence)
                    and e.phase==rule.phase and getattr(e,rule.condition_kind)==rule.condition_value] if cell.status=='applicable' else []
        status=('NOT_APPLICABLE' if cell.status=='not_applicable' else 'APPLICABILITY_UNKNOWN' if cell.status=='unknown'
                else 'UNMATCHED' if not candidates else 'MATCHED' if len(candidates)==1 else 'AMBIGUOUS')
        match=candidates[0] if status=='MATCHED' else None
        rows.append(dict(check_id=cell.check_id,recording_id=route.recording_id,route_version=route.version,
            route_hash=route.content_hash,occurrence=route.occurrence,status=status,
            candidate_count=len(candidates),step_id=match.step_id if match else None,
            phase=match.phase if match else None,matched_state=match.state if match else None,
            event_id=match.event_id if match else None,required_evidence=list(rule.required_evidence)))
    return dict(contract='synthetic-timing-match.v1',metadata_hash=metadata_hash,
                rules=[asdict(r) for r in rules],rows=rows)
