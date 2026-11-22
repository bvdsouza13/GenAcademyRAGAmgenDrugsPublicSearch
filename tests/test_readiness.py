import json
from types import SimpleNamespace

import pytest

from amgen_explorer.models import TeachingResponse
from test_indexing import config


def readiness_service(config, response):
    return SimpleNamespace(config=config,
        connection_status=lambda: {'pinecone': {'ok': True}, 'openai': {'ok': True}},
        library_version=lambda: {'run_id': 'r', 'full_library': True},
        library_corpus=lambda rid: SimpleNamespace(
            documents=[SimpleNamespace(id='doc', product_id='product')],
            products=[SimpleNamespace(id='product', name='ALPHA')]),
        search_library=lambda *args, **kw: SimpleNamespace(degraded=False, hits=[{'id': 'c'}]),
        answer=lambda *args, **kw: response)


def test_model_access_cannot_mask_failed_generation(config):
    from amgen_explorer.readiness import check_readiness
    response = TeachingResponse('Source only', [{'id': 'c'}], abstained=True,
                                usage={'source_fallback': True, 'provider_problem': True})
    report = check_readiness(readiness_service(config, response), require_generation=True)
    assert report['model_access']['ok']
    assert not report['ok'] and report['generation']['state'] == 'provider_unavailable'
    assert config.openai_api_key not in json.dumps(report)


def test_generation_requires_supported_answer_and_citations(config):
    from amgen_explorer.readiness import check_readiness
    report = check_readiness(readiness_service(config, TeachingResponse('Verified', [{'id': 'c'}], usage={'explanation_verified':True})), require_generation=True)
    assert report['ok'] and report['generation']['state'] == 'verified'
    assert report['generation']['citation_count'] == 1
    path = config.root / 'data/health/readiness.json'
    assert json.loads(path.read_text())['checked_at'] == report['checked_at']


def test_access_check_does_not_generate_unless_requested(config):
    from amgen_explorer.readiness import check_readiness
    service = readiness_service(config, None)
    service.answer = lambda *a, **kw: pytest.fail('Unrequested generation')
    report = check_readiness(service)
    assert report['generation']['state'] == 'not_checked'
    assert report['ok']


def test_citations_without_verified_explanation_do_not_pass_generation(config):
    from amgen_explorer.readiness import check_readiness
    response=TeachingResponse('Unverified', [{'id':'c'}], usage={'explanation_verified':False})
    report=check_readiness(readiness_service(config,response),require_generation=True)
    assert not report['ok'] and not report['generation']['ok']
