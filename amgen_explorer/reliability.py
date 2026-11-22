"""Bounded provider work; no credentials, provider calls or waits on import."""
from contextlib import contextmanager
from contextvars import ContextVar
from email.utils import parsedate_to_datetime
import math
import random
import time

DEFAULTS = {'response_deadline_seconds': 60, 'max_attempts': 4,
            'retry_budget_seconds': 60, 'backoff_base_seconds': 1,
            'backoff_cap_seconds': 8}
_current = ContextVar('medicine_response_deadline', default=None)


class Deadline:
    def __init__(self, seconds, *, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self):
        return max(0.0, self.end - self.clock())


@contextmanager
def deadline_scope(seconds, *, clock=time.monotonic):
    parent = _current.get()
    own = Deadline(seconds, clock=clock)
    # Keep both clocks: tests and nested callers need not share a clock origin.
    scopes = (() if parent is None else parent) + (own,)
    token = _current.set(scopes)
    try:
        check_deadline()
        yield own
    finally:
        _current.reset(token)


def deadline_timeout(request_timeout):
    from .connectivity import ProviderError
    scopes = _current.get() or ()
    remaining = min([float(request_timeout)] + [item.remaining() for item in scopes])
    if remaining <= 0:
        raise ProviderError('Response deadline', 408)
    return remaining


def check_deadline():
    deadline_timeout(float('inf'))


def parse_retry_after(value, *, now=None):
    """Return only a finite delay; never retain a reflected header string."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                return None
            delay = max(0.0, stamp.timestamp() - (time.time() if now is None else now))
        except (TypeError, ValueError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay >= 0 else None


def settings_for(settings=None):
    supplied = settings or {}
    supplied = supplied.get('reliability', supplied)
    return {**DEFAULTS, **{key: value for key, value in supplied.items() if key in DEFAULTS}}


def retry_delay(attempt, error, *, settings=None, rng=None):
    options = settings_for(settings)
    sample = (rng or random.random)()
    base = min(options['backoff_cap_seconds'], options['backoff_base_seconds'] * (2 ** min(attempt, 20)))
    jittered = min(options['backoff_cap_seconds'], base * (1 + .25 * max(0, min(1, sample))))
    retry_after = getattr(error, 'retry_after', None)
    return max(jittered, retry_after) if retry_after is not None else jittered


def retry_call(operation, *, settings=None, sleep=time.sleep, clock=time.monotonic, rng=None, on_retry=None):
    """Retry only known transient provider faults within the total retry budget.

    Upload orchestration may own its own checkpointed retry loop. It can consume
    retry_delay directly; request_json deliberately remains a single attempt.
    """
    from .connectivity import ProviderError
    options = settings_for(settings)
    with deadline_scope(options['retry_budget_seconds'], clock=clock) as deadline:
        for attempt in range(options['max_attempts']):
            check_deadline()
            try:
                result = operation()
                check_deadline()
                return result
            except ProviderError as error:
                if not error.retryable or attempt + 1 >= options['max_attempts']:
                    raise
                delay = retry_delay(attempt, error, settings=options, rng=rng)
                if delay >= min(deadline.remaining(), deadline_timeout(float('inf'))):
                    raise
                if on_retry:
                    on_retry(error, attempt + 1)
                sleep(delay)
