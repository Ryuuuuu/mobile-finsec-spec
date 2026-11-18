"""Active structural supervisor; historical P3 supervisor is loaded only on request."""
from .structure_supervisor import StructureSupervisor, MockExecutor


def __getattr__(name):
    # Compatibility for historical demos. Active tests use StructureSupervisor.
    if name in ('Supervisor', 'StopRun', 'Handle'):
        from . import legacy_supervisor
        return getattr(legacy_supervisor, name)
    raise AttributeError(name)
