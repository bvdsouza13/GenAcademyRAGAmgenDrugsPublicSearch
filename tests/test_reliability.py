"""Bound request/retry work and preserve safe errors, using an explicit clock."""
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.error import HTTPError

import pytest

from amgen_explorer.connectivity import ProviderError, request_json
from test_indexing import config


def test_deadline_caps_requests_and_rejects_late_work():
    from amgen_explorer.reliability import deadline_scope, deadline_timeout, check_deadline
    now = [10.0]
    with deadline_scope(5, clock=lambda: now[0]):
        assert deadline_timeout(30) == 5
        now[0] = 14
        assert deadline_timeout(30) == 1
        now[0] = 15
        with pytest.raises(ProviderError):
            check_deadline()
    assert deadline_timeout(30) == 30


def test_nested_scope_cannot_extend_parent_deadline():
    from amgen_explorer.reliability import deadline_scope, deadline_timeout
    now = [0.0]
    with deadline_scope(5, clock=lambda: now[0]):
        now[0] = 2
        with deadline_scope(100, clock=lambda: now[0]):
            assert deadline_timeout(30) == 3
        assert deadline_timeout(30) == 3


@pytest.mark.parametrize('status', [401, 403])
def test_authentication_failure_has_no_retry(status):
    from amgen_explorer.reliability import retry_call
    calls = []
    def operation():
        calls.append(1)
        raise ProviderError('Cloud', status)
    with pytest.raises(ProviderError):
        retry_call(operation, sleep=lambda _: pytest.fail('Unexpected wait'))
    assert len(calls) == 1


def test_retry_count_backoff_and_budget_are_bounded():
    from amgen_explorer.reliability import retry_call
    now = [0.0]; delays = []; calls = []
    def sleep(delay):
        delays.append(delay); now[0] += delay
    def operation():
        calls.append(1)
        raise ProviderError('Cloud', 503)
    with pytest.raises(ProviderError):
        retry_call(operation, sleep=sleep, clock=lambda: now[0], rng=lambda: 0)
    assert len(calls) == 4
    assert delays == [1, 2, 4]
    calls.clear(); delays.clear(); now[0] = 0
    with pytest.raises(ProviderError):
        retry_call(operation, settings={'retry_budget_seconds': 2}, sleep=sleep,
                   clock=lambda: now[0], rng=lambda: 0)
    assert len(calls) == 2 and delays == [1]


def test_retry_after_never_shortens_server_delay_or_exceeds_budget():
    from amgen_explorer.reliability import retry_call
    now = [0.0]; calls = []; delays = []
    def operation():
        calls.append(1)
        raise ProviderError('Cloud', 429, retry_after=120)
    with pytest.raises(ProviderError):
        retry_call(operation, settings={'retry_budget_seconds': 60}, sleep=delays.append,
                   clock=lambda: now[0])
    assert len(calls) == 1 and delays == []


@pytest.mark.parametrize('value,expected', [('12', 12), ('-2', None), ('garbage-secret', None), ('NaN', None)])
def test_retry_header_is_parsed_without_reflecting_remote_text(monkeypatch, value, expected):
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError('https://private.invalid', 429, 'private response', {'Retry-After': value}, None)
    monkeypatch.setattr('amgen_explorer.connectivity.build_opener', lambda *args: Opener())
    with pytest.raises(ProviderError) as error:
        request_json('https://api.openai.com/v1/models', method='GET')
    assert error.value.retry_after == expected
    assert 'private' not in str(error.value) and 'secret' not in str(error.value)


def test_http_date_retry_header_and_jitter_are_bounded():
    from amgen_explorer.reliability import parse_retry_after, retry_delay
    stamp = format_datetime(datetime.fromtimestamp(120, timezone.utc), usegmt=True)
    assert parse_retry_after(stamp, now=100) == 20
    assert parse_retry_after(stamp, now=130) == 0
    assert retry_delay(0, ProviderError('Cloud', 503), rng=lambda: 1) == 1.25
    assert retry_delay(10, ProviderError('Cloud', 503), rng=lambda: 1) == 8


def test_legacy_configuration_works_and_optional_reliability_is_validated(config):
    assert config.validate() == []
    config.settings['reliability'] = {'response_deadline_seconds': 60, 'max_attempts': 4,
                                    'retry_budget_seconds': 60, 'backoff_base_seconds': 1,
                                    'backoff_cap_seconds': 8}
    assert config.validate() == []
    config.settings['reliability']['response_deadline_seconds'] = 0
    assert any('response_deadline_seconds' in error for error in config.validate())


def test_success_returned_after_deadline_is_not_accepted():
    from amgen_explorer.reliability import retry_call
    now = [0.0]
    def operation():
        now[0] = 61
        return {'unverified': 'late'}
    with pytest.raises(ProviderError):
        retry_call(operation, clock=lambda: now[0])
