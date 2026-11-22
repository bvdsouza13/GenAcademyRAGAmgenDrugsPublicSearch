"""Fault simulations and explicit known search-quality gaps (no live APIs).

Strict xfails describe desirable behavior that currently fails; they are not
passing acceptance tests for the present ranking. Remove xfail when addressed.
"""
from dataclasses import asdict
import copy
import json
from pathlib import Path

import pytest

from amgen_explorer.connectivity import ProviderError
from amgen_explorer.indexing import manifest_records
from amgen_explorer.models import Corpus, Document, Product
from amgen_explorer.search import build_search_artifact, search_library
from test_indexing import FakeDocuments, config, plan, service


@pytest.fixture(params=[True, False], ids=['fts5', 'fallback-token-engine'])
def diagnostic_library(config, plan, request):
    products = [Product('act', 'ACTIMMUNE', 'interferon gamma-1b', ['act-label']),
                Product('other', 'OTHER', 'other-generic', ['other-label'])]
    docs = [Document('act-label', 'act', 'act.pdf', 'a'*64, 1, '2025', ''),
            Document('other-label', 'other', 'other.pdf', 'b'*64, 1, '2025', '')]
    texts = [('act', 'act-label', 'a'*64, 'What is ACTIMMUNE? ACTIMMUNE is a medicine.'),
             ('act', 'act-label', 'a'*64, 'ACTIMMUNE binds to specific receptors.'),
             ('act', 'act-label', 'a'*64, 'ACTIMMUNE is stored refrigerated.'),
             ('other', 'other-label', 'b'*64, 'What is OTHER? OTHER is a medicine.')]
    template = plan.chunks[0]
    plan.chunks = []
    for i, (pid, did, sha, text) in enumerate(texts):
        chunk = copy.deepcopy(template)
        chunk.id = f'diagnostic-{i}'
        chunk.text = text
        start = i * 100
        chunk.metadata.update(product_id=pid, document_id=did, document_sha256=sha,
                              source_text=text, section_title='About this medicine',
                              source_spans=json.dumps([{'page':1, 'start':start, 'end':start+len(text), 'archive_block_id':did+'-page'}]))
        plan.chunks.append(chunk)
    fake = FakeDocuments()
    run = service(config, fake).ingest(plan)
    records = manifest_records(run, config)
    corpus = Corpus(Path('diagnostic.xml'), plan.xml_hash, products, docs, [])
    run['search_artifact'] = asdict(build_search_artifact(run, records, corpus, config, use_fts5=request.param))
    fake.search = lambda *args: []
    return run, records, corpus, fake


@pytest.mark.xfail(strict=True, reason='Known gap: OR stopwords and document round-robin introduce unrelated products.')
def test_named_question_keeps_unrelated_boilerplate_out(config, diagnostic_library):
    run, _, corpus, fake = diagnostic_library
    result = search_library('What is ACTIMMUNE?', run, config, corpus, client=fake, limit=2)
    assert result.hits and all(h['product_id'] == 'act' for h in result.hits)


@pytest.mark.xfail(strict=True, reason='Known gap: weak semantic neighbors are accepted without an answerability/relevance gate.')
def test_irrelevant_semantic_neighbor_does_not_become_search_result(config, diagnostic_library):
    run, records, corpus, fake = diagnostic_library
    fake.search = lambda *args: [{**records[-1], '_score':0.000001}]
    result = search_library('qzxvnmqzxvnm', run, config, corpus, client=fake)
    assert result.hits == []


@pytest.mark.xfail(strict=True, reason='Known gap: conversational stopwords alone match medicine boilerplate.')
def test_stopword_only_query_does_not_return_drug_results(config, diagnostic_library):
    run, _, corpus, fake = diagnostic_library
    result = search_library('what is', run, config, corpus, client=fake)
    assert result.hits == []


@pytest.mark.parametrize('status', [401, 403, 429, 500, 503])
def test_provider_fault_preserves_verified_local_results_and_labels_mode(config, diagnostic_library, status):
    run, _, corpus, fake = diagnostic_library
    def fail(*args):
        raise ProviderError('Pinecone', status)
    fake.search = fail
    result = search_library('ACTIMMUNE', run, config, corpus, client=fake)
    assert len(result.hits) == 3
    assert {h['product_id'] for h in result.hits} == {'act'}
    assert result.degraded and any('degraded' in warning for warning in result.warnings)


def test_explicit_product_filter_prevents_question_boilerplate_pollution(config, diagnostic_library):
    run, _, corpus, fake = diagnostic_library
    result = search_library('What is ACTIMMUNE?', run, config, corpus, client=fake, product_ids=['act'])
    assert len(result.hits) == 3 and all(h['product_id'] == 'act' for h in result.hits)


def test_tampered_semantic_text_is_excluded(config, diagnostic_library):
    run, records, corpus, fake = diagnostic_library
    fake.search = lambda *args: [{**records[0], 'source_text':'Changed source content'}]
    result = search_library('qzxvnmqzxvnm', run, config, corpus, client=fake)
    assert result.hits == [] and any('verification' in w for w in result.warnings)


def test_no_match_and_no_semantic_evidence_is_empty(config, diagnostic_library):
    run, _, corpus, fake = diagnostic_library
    result = search_library('qzxvnmqzxvnm', run, config, corpus, client=fake)
    assert result.hits == []
