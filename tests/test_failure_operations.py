"""Operational failure probes. Strict xfails are unresolved acceptance gaps.

Passing characterization tests explicitly describe metric limitations; they do
not assert that retrieval quality or cloud generation is correct.
"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from amgen_explorer.evaluation import score_case
from amgen_explorer.models import TeachingResponse
from test_app_flows import ROOT
from test_library_build import library_service
from test_search_experience import library_app


def test_current_global_metrics_do_not_measure_irrelevant_tail():
    case = {'expected_document_ids': ['intended'], 'expected_spans': [
        {'document_id': 'intended', 'document_sha256': 'hash', 'page': 1, 'start': 0, 'end': 4}]}
    def hit(doc):
        return {'text': 'text', 'metadata': {'document_id': doc, 'document_sha256': 'hash',
                'source_spans': [{'page': 1, 'start': 0, 'end': 4}]}}
    relevant = score_case(case, [hit('intended')], evidence_budget=4000)
    noisy = score_case(case, [hit('intended')] + [hit(f'irrelevant-{i}') for i in range(9)], evidence_budget=4000)
    # This is the blind spot being documented, not an accuracy assertion.
    for key in ('document_recall_at_k', 'reciprocal_rank', 'quote_coverage', 'contamination_rate'):
        assert noisy[key] == relevant[key]
    assert noisy['document_recall_at_k'] == noisy['quote_coverage'] == 1
    assert noisy['contamination_rate'] == 0


@pytest.mark.xfail(strict=True, reason='OPS-01: status exceptions escape the Home page without recovery UI.')
def test_status_failure_is_contained_on_home_page(library_app):
    at, service = library_app
    service.library_status = Mock(side_effect=ValueError('Malformed historical run manifest'))
    at.run()
    assert not at.exception
    assert at.error


@pytest.mark.xfail(strict=True, reason='OPS-02: corrupt active pointer stops rendering before Admin navigation.')
def test_unreadable_active_pointer_keeps_recovery_navigation(library_app):
    at, service = library_app
    service.active = Mock(side_effect=ValueError('Unreadable active pointer'))
    at.run()
    assert not at.exception
    assert any('Admin' in radio.options for radio in at.sidebar.radio)


def test_demo_remains_available_when_configuration_cannot_load(monkeypatch):
    factory = Mock(side_effect=ValueError('Malformed configuration'))
    monkeypatch.setitem(sys.modules, 'amgen_explorer.service', SimpleNamespace(ExplorerService=factory))
    at = AppTest.from_file(str(ROOT / 'app.py'))
    at.query_params['demo'] = '1'
    at.run()
    assert not at.exception and at.button(key='demo_next')
    factory.assert_not_called()


@pytest.mark.xfail(strict=True, reason='OPS-03: live --chat smoke test reports passed when every explanation provider call fails.')
def test_live_chat_smoke_distinguishes_provider_failure_from_generation_readiness(monkeypatch, tmp_path):
    import scripts.live_library_check as smoke
    docs = ['doc-actimmune-prescribing-information',
            'doc-repatha-prescribing-information-dry-natural-rubber',
            'doc-repatha-other-variant', 'doc-tezspire-prescribing-information']
    products = ['product-actimmune', 'product-repatha', 'product-repatha', 'product-tezspire']
    run = {'run_id': 'fake', 'full_library': True, 'record_count': 4,
           'document_ids': docs, 'product_ids': sorted(set(products)), 'coverage': {}, 'xml_hash': 'hash'}
    result = SimpleNamespace(hits=[{'metadata': {'product_id': p, 'document_id': d}}
                                 for p, d in zip(products, docs)], degraded=False, latency_ms=1, usage={})
    service = SimpleNamespace(library_version=lambda: run, search_library=lambda *a, **kw: result,
        source_pdf=lambda *a: b'%PDF', answer=lambda *a, **kw: TeachingResponse(
            'Provider unavailable; source quotation only.', citations=[{'document_id': docs[0]}],
            abstained=True, usage={'provider_problem': True, 'source_fallback': True, 'explanation_verified': False}))
    monkeypatch.setattr(smoke, 'ExplorerService', lambda: service)
    monkeypatch.setattr(smoke, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['live_library_check.py', '--chat'])
    assert smoke.main() != 0


def test_readiness_audit_default_is_local_and_keeps_pointer(library_service):
    from scripts.assess_failure_modes import assess
    service, fake = library_service
    run = service.build_library(service.chunk_config())
    folder = service.config.root / 'evals'
    folder.mkdir()
    (folder / 'global-search.jsonl').write_text(json.dumps({'id': 'local', 'expected_document_ids': run['document_ids']}) + '\n')
    service._evidence = Mock(side_effect=AssertionError('Cloud retrieval was not requested'))
    writes = len(fake.writes)
    report = assess(service)
    assert report['active_pointer_unchanged'] and report['records'] == run['record_count']
    assert not report['live'] and report['evidence_probes'] == []
    service._evidence.assert_not_called()
    assert len(fake.writes) == writes
    verified = assess(service, verify_remote=True)
    assert verified['remote_verification']['ok'] and verified['active_pointer_unchanged']
    assert len(fake.writes) == writes
    fake.records[run['namespace']].clear()
    missing = assess(service, verify_remote=True)
    assert not missing['remote_verification']['ok']
    assert len(fake.writes) == writes
