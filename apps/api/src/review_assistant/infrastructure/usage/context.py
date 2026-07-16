from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UsageContext:
    purpose: str = "unspecified"
    course_id: str | None = None
    session_id: str | None = None


_current: ContextVar[UsageContext] = ContextVar("usage_context", default=UsageContext())


def current_usage_context() -> UsageContext:
    return _current.get()


@contextmanager
def usage_scope(purpose: str, *, course_id: str | None = None, session_id: str | None = None):
    token = _current.set(UsageContext(purpose, course_id, session_id))
    try:
        yield
    finally:
        _current.reset(token)
