"""Paid repair attempts survive failures without mutating retained run identity."""
import json

import pytest

from amgen_explorer.connectivity import ProviderError
from amgen_explorer.library_health import latest_report
from amgen_explorer.retention import plan_cleanup
from test_failure_recovery import isolated_library


@pytest.mark.parametrize('entrypoint',['repair','build'])
@pytest.mark.parametrize('interrupted',[False,True])
def test_repair_usage_and_uncertainty_are_durable(isolated_library,monkeypatch,entrypoint,interrupted):
    service,fake,_=isolated_library
    upsert=fake.upsert
    def paid(namespace,rows):
        result=upsert(namespace,rows)
        result['usage']={'embed_total_tokens':100,'secret':'never save'}
        return result
    monkeypatch.setattr(fake,'upsert',paid)
    run=service.build_library(service.chunk_config())
    path=service.config.path('manifest_dir')/(run['run_id']+'.json')
    original=path.read_bytes()
    fake.records[run['namespace']].clear()
    calls=0
    def flaky(namespace,rows):
        nonlocal calls
        calls+=1
        if calls==1:raise ProviderError('secret provider payload',429)
        if interrupted and calls==3:raise ProviderError('secret provider payload',400)
        return paid(namespace,rows)
    monkeypatch.setattr(fake,'upsert',flaky)
    if entrypoint=='repair':
        report=service.verify_library(run['run_id'],repair=True)
        assert report['outcome']==('unavailable' if interrupted else 'verified')
    elif interrupted:
        with pytest.raises(ProviderError):service.build_library(service.chunk_config())
    else:service.build_library(service.chunk_config())
    # These totals must describe repair calls, separate from the initial build.
    operations=list((service.config.root/'data/health/operations').glob('*.json'))
    assert len(operations)==1
    operation=json.loads(operations[0].read_text())
    assert operation['usage']=={'embed_total_tokens':100 if interrupted else run['record_count']*100}
    assert operation['usage_may_include_unreported_retries'] is True
    assert operation['status']==('interrupted' if interrupted else 'completed')
    assert 'secret' not in json.dumps(operation)
    assert path.read_bytes()==original
    retained=next(r for r in plan_cleanup(service.config).runs if r['run_id']==run['run_id'])
    assert retained['provider_usage_scope']=='initial_and_resumed_ingestion'
    assert retained['provider_usage']==run['usage']
    assert retained['repair_provider_usage']==operation['usage']
    assert retained['repair_usage_may_be_incomplete'] is True
    if entrypoint=='repair':
        assert latest_report(service.config,run['run_id'])['repair_usage']['usage']==operation['usage']


def test_missing_repair_usage_is_unknown_not_zero_cost(isolated_library):
    service,fake,_=isolated_library
    run=service.build_library(service.chunk_config())
    fake.records[run['namespace']].clear()
    report=service.verify_library(run['run_id'],repair=True)
    assert report['outcome']=='verified'
    operation=report['repair_usage']
    assert operation['usage']=={'embed_total_tokens':0}
    assert operation['usage_may_include_unreported_retries'] is True
    assert operation['usage_scope']=='reported_embedding_tokens_only'


def test_repair_checkpoint_is_written_before_paid_request_and_survives_interrupt(isolated_library,monkeypatch):
    service,fake,_=isolated_library
    run=service.build_library(service.chunk_config())
    fake.records[run['namespace']].clear()
    def interrupt(namespace,rows):
        paths=list((service.config.root/'data/health/operations').glob('*.json'))
        assert len(paths)==1
        ongoing=json.loads(paths[0].read_text())
        assert ongoing['status']=='in_progress' and ongoing['request_in_progress'] is True
        raise KeyboardInterrupt()
    monkeypatch.setattr(fake,'upsert',interrupt)
    with pytest.raises(KeyboardInterrupt):service.verify_library(run['run_id'],repair=True)
    operation=json.loads(next((service.config.root/'data/health/operations').glob('*.json')).read_text())
    assert operation['status']=='interrupted'
    assert operation['usage_may_include_unreported_retries'] is True


def test_multiple_repairs_aggregate_reported_usage_without_recounting_ingestion(isolated_library,monkeypatch):
    service,fake,_=isolated_library
    run=service.build_library(service.chunk_config())
    upsert=fake.upsert
    def paid(namespace,rows):
        result=upsert(namespace,rows)
        result['usage']={'embed_total_tokens':25}
        return result
    monkeypatch.setattr(fake,'upsert',paid)
    for _ in range(2):
        del fake.records[run['namespace']][next(iter(fake.records[run['namespace']]))]
        assert service.verify_library(run['run_id'],repair=True)['outcome']=='verified'
    retained=next(r for r in plan_cleanup(service.config).runs if r['run_id']==run['run_id'])
    assert retained['provider_usage']=={'embed_total_tokens':0}
    assert retained['repair_operation_count']==2
    assert retained['repair_provider_usage']=={'embed_total_tokens':50}
    assert retained['repair_usage_may_be_incomplete'] is False
