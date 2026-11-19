"""Fixed read-only disposable QA state reader; no screenshots/source/packet data."""
import re
import time

PACKAGE='dev.finsec.qa.network'
RESOURCE=PACKAGE+':id/state'
ELEMENT='element-6066-11e4-a52e-4f735466cecf'
ALLOWED={'ready':'QA_READY','sent:1':'QA_SENT'}


def read_network_qa_state(adapter, *, budget=1.0):
    if adapter.package!=PACKAGE or not adapter.session or adapter.uncertain:
        raise ValueError('QA_STATE_SCOPE_UNAVAILABLE')
    if type(budget) not in (int,float) or not 0<budget<=1:
        raise ValueError('QA_STATE_BUDGET_INVALID')
    deadline=time.monotonic()+budget
    def query(method,path,data=None):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('QA_STATE_DEADLINE')
        try:
            result=adapter.request(method,'/session/'+adapter.session+path,data,timeout=remaining)
        except Exception:
            raise RuntimeError('QA_STATE_READ_FAILED') from None
        if time.monotonic()>deadline:raise TimeoutError('QA_STATE_DEADLINE')
        return result
    if query('GET','/appium/device/current_package')!=PACKAGE:
        raise ValueError('QA_STATE_TARGET_NOT_FOREGROUND')
    elements=query('POST','/elements',{'using':'id','value':RESOURCE})
    if not isinstance(elements,list) or len(elements)!=1:
        raise ValueError('QA_STATE_NOT_UNIQUE')
    element=elements[0].get(ELEMENT) if isinstance(elements[0],dict) else None
    if not isinstance(element,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',element):
        raise ValueError('QA_STATE_ELEMENT_INVALID')
    value=query('GET','/element/'+element+'/text')
    # Unknown raw text is discarded; the host records only exclusion, never the value.
    return ALLOWED.get(value,'UNSUPPORTED_QA_STATE') if isinstance(value,str) else 'UNSUPPORTED_QA_STATE'
