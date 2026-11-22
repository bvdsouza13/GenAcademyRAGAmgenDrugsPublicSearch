"""Global discovery keeps lexical results useful and every source scope pinned."""
from dataclasses import asdict
import copy
import json
from pathlib import Path

import pytest

from amgen_explorer.models import Corpus, Document, Product
from amgen_explorer.indexing import IndexService, atomic_json, manifest_records
from test_indexing import config, plan, FakeDocuments, service


@pytest.fixture
def library(config, plan):
    sources = [
        ('act', 'act-label', 'ACTIMMUNE', 'interferon gamma-1b', 'Avoid natural rubber latex in the stopper.', 'Warnings'),
        ('repatha', 'repatha-pen', 'Repatha', 'evolocumab', 'Store refrigerated at 2 to 8 degrees.', 'Storage'),
        ('repatha', 'repatha-syringe', 'Repatha', 'evolocumab', 'The syringe contains natural rubber latex.', 'Device'),
        ('other', 'other-label', 'Other', 'other-generic', 'Store refrigerated away from direct light.', 'Storage'),
    ]
    prototype = plan.chunks[0]
    chunks = []
    products = {}
    docs = []
    for i, (pid, did, brand, generic, text, heading) in enumerate(sources):
        c = copy.deepcopy(prototype)
        c.id = f'chunk-{i}'
        c.text = text
        c.metadata.update(product_id=pid, document_id=did, document_sha256=str(i)*64,
            section_title=heading, source_text=text,
            source_spans=json.dumps([{'page':1,'start':0,'end':len(text),'archive_block_id':did+'-page'}]),
            filename=did+'.pdf')
        chunks.append(c)
        products.setdefault(pid, Product(pid, brand, generic, [])).document_ids.append(did)
        docs.append(Document(did, pid, did+'.pdf', str(i)*64, 1, '2025', did))
    plan.chunks = chunks
    fake = FakeDocuments()
    run = service(config, fake).ingest(plan)
    corpus = Corpus(Path('pinned.xml'), plan.xml_hash, list(products.values()), docs, [])
    return run, manifest_records(run, config), corpus, fake


def make_searchable(config, library, **kwargs):
    from amgen_explorer.search import build_search_artifact
    run, records, corpus, fake = library
    run['search_artifact'] = asdict(build_search_artifact(run, records, corpus, config, **kwargs))
    return run, records, corpus, fake


def test_body_content_finds_multiple_medicines_and_variants(config, library):
    from amgen_explorer.search import search_library
    run, _, corpus, fake = make_searchable(config, library)
    fake.search = lambda *args: []
    result = search_library('latex', run, config, corpus, client=fake)
    assert {h['metadata']['product_id'] for h in result.hits} == {'act','repatha'}
    assert {h['metadata']['document_id'] for h in result.hits} == {'act-label','repatha-syringe'}
    assert {(g['product_id'],g['document_id']) for g in result.groups} == {('act','act-label'),('repatha','repatha-syringe')}
    assert result.run_id == run['run_id'] and result.xml_hash == corpus.xml_hash
    assert all(h['metadata']['source_spans'] and h['run_id']==run['run_id'] for h in result.hits)


@pytest.mark.parametrize('query,expected', [('ACTIMMUNE', {'act-label'}), ('interferon gamma-1b', {'act-label'}), ('evolocumab', {'repatha-pen','repatha-syringe'}), ('Warnings', {'act-label'})])
def test_names_generic_aliases_and_headings_are_indexed(config, library, query, expected):
    from amgen_explorer.search import search_library
    run, _, corpus, fake = make_searchable(config, library)
    fake.search = lambda *args: []
    result = search_library(query, run, config, corpus, client=fake)
    assert {h['metadata']['document_id'] for h in result.hits} == expected


def test_optional_filters_apply_to_local_and_cloud_results(config, library):
    from amgen_explorer.search import search_library
    run, records, corpus, fake = make_searchable(config, library)
    observed = []
    def cloud(namespace, query, filters, limit):
        observed.append((namespace, filters))
        return records
    fake.search = cloud
    result = search_library('latex', run, config, corpus, client=fake,
                            product_ids=['repatha'], document_ids=['repatha-syringe'])
    assert [h['metadata']['document_id'] for h in result.hits] == ['repatha-syringe']
    clauses = observed[0][1]['$and']
    assert {'xml_hash':{'$eq':run['xml_hash']}} in clauses
    assert {'product_id':{'$in':['repatha']}} in clauses
    assert {'document_id':{'$in':['repatha-syringe']}} in clauses
    assert observed[0][0] == run['namespace']
    assert any('excluded' in warning for warning in result.warnings)


def test_semantic_outage_is_explicit_and_keeps_exact_lexical_sources(config, library):
    from amgen_explorer.search import search_library
    from amgen_explorer.connectivity import ProviderError
    run, _, corpus, fake = make_searchable(config, library)
    def outage(*args):
        raise ProviderError('Pinecone', 503)
    fake.search = outage
    result = search_library('latex', run, config, corpus, client=fake)
    assert len(result.hits) == 2 and result.degraded
    assert any('local text search' in warning.lower() for warning in result.warnings)
    assert result.latency_ms >= 0 and isinstance(result.usage, dict)


def test_semantic_fusion_rejects_tampered_hit_and_keeps_valid_nonlexical_match(config, library):
    from amgen_explorer.search import search_library
    run, records, corpus, fake = make_searchable(config, library)
    altered = {**records[0], 'source_text':'invented'}
    fake.search = lambda *args: [altered, {**records[1], '_score':.9}]
    result = search_library('keep cold', run, config, corpus, client=fake)
    assert [h['id'] for h in result.hits] == ['chunk-1']
    assert result.hits[0]['text'] == 'Store refrigerated at 2 to 8 degrees.'
    assert any('verification' in w for w in result.warnings)


@pytest.mark.parametrize('query', ['', '  ', 'x'*2048])
def test_invalid_queries_fail_before_semantic_call(config, library, query):
    from amgen_explorer.search import search_library
    run, _, corpus, fake = make_searchable(config, library)
    def must_not_call(*args):
        raise AssertionError('Semantic embedding called for invalid query')
    fake.search = must_not_call
    with pytest.raises(ValueError):
        search_library(query, run, config, corpus, client=fake)


def test_overlap_dedup_does_not_merge_source_variants(config, library):
    from amgen_explorer.search import build_search_artifact, search_library
    run, _, corpus, fake = library
    records = manifest_records(run, config)
    # Duplicate source passage under another chunk id: a legitimate alternate chunk plan.
    p = copy.deepcopy(plan.__wrapped__())
    p.chunks = []
    from amgen_explorer.models import Chunk
    for r in records + [{**records[0], '_id':'overlap'}]:
        p.chunks.append(Chunk(r['_id'], r['chunk_text'], {k:v for k,v in r.items() if k not in {'_id','chunk_text'}}, 100))
    p.xml_hash=run['xml_hash']; p.config_hash=run['config_hash']; p.review_hash=run['review_hash']
    run = service(config, fake).ingest(p)
    run['search_artifact'] = asdict(build_search_artifact(run, manifest_records(run, config), corpus, config))
    fake.search = lambda *args: []
    result = search_library('latex', run, config, corpus, client=fake)
    assert len(result.hits) == 2
    result = search_library('evolocumab', run, config, corpus, client=fake)
    assert {h['metadata']['document_id'] for h in result.hits} == {'repatha-pen','repatha-syringe'}


def test_fallback_token_search_is_deterministic_and_escapes_fts_syntax(config, library):
    from amgen_explorer.search import search_library
    run, _, corpus, fake = make_searchable(config, library, use_fts5=False)
    fake.search = lambda *args: []
    first = search_library('latex OR " rubber:*', run, config, corpus, client=fake)
    second = search_library('latex OR " rubber:*', run, config, corpus, client=fake)
    assert [h['id'] for h in first.hits] == [h['id'] for h in second.hits]
    assert {h['metadata']['product_id'] for h in first.hits} == {'act','repatha'}


def test_semantic_configuration_check_failure_retains_local_text_search(config, library):
    from amgen_explorer.search import search_library
    from scripts.setup_pinecone import SetupError
    run, _, corpus, fake = make_searchable(config, library)
    fake.host = ''
    def unavailable():
        raise SetupError('Pinecone unavailable')
    fake.check = unavailable
    result = search_library('latex', run, config, corpus, client=fake)
    assert len(result.hits)==2 and result.degraded
    assert any('local text search' in w.lower() for w in result.warnings)


def test_repeated_text_at_distinct_source_offsets_keeps_both_citations(config, library, plan):
    from amgen_explorer.search import build_search_artifact, search_library
    _, _, corpus, fake = library
    extra = copy.deepcopy(plan.chunks[0])
    extra.id = 'repeated-at-other-offset'
    extra.metadata.update(section_id='different-section', section_title='Different context',
        source_spans=json.dumps([{'page':1,'start':100,'end':100+len(extra.text),'archive_block_id':'act-label-page'}]))
    plan.chunks.append(extra)
    plan.fingerprint = 'e'*64
    run = service(config, fake).ingest(plan)
    records = manifest_records(run, config)
    run['search_artifact'] = asdict(build_search_artifact(run, records, corpus, config))
    fake.search = lambda *args: []
    result = search_library('latex', run, config, corpus, client=fake)
    act_hits = [h for h in result.hits if h['metadata']['document_id']=='act-label']
    assert len(act_hits)==2
    assert {h['metadata']['source_spans'][0]['start'] for h in act_hits} == {0,100}


def test_search_local_is_provider_free_with_identical_pins(config, library, monkeypatch):
    from amgen_explorer import search
    run, _, corpus, _ = make_searchable(config, library)
    def forbidden(*args, **kwargs):
        raise AssertionError('Local discovery constructed a provider')
    monkeypatch.setattr(search, 'DocumentsClient', forbidden)
    local=getattr(search,'search_local',None)
    assert callable(local), 'Explicit local search must exist'
    result=local('latex',run,config,corpus)
    assert {h['document_id'] for h in result.hits}=={'act-label','repatha-syringe'}
    assert result.outcome=='results' and all(h['run_id']==run['run_id'] for h in result.hits)


def test_local_suggestions_do_not_silently_substitute_medicine(config, library):
    from amgen_explorer import search
    run, _, corpus, _ = make_searchable(config, library)
    local=getattr(search,'search_local',None)
    assert callable(local)
    result=local('What is ACTIMUNE?',run,config,corpus)
    assert result.hits==[] and result.outcome=='clarification'
    assert 'ACTIMMUNE' in result.suggestions


def test_query_interpretation_keeps_negation_units_and_token_boundaries(config, library):
    from amgen_explorer import search
    run, _, corpus, _ = make_searchable(config, library)
    intent=getattr(search,'analyze_query',None)
    assert callable(intent)
    query=intent('Could you tell me about Repatha not 140 mg?',corpus)
    assert query.product_candidates==['repatha']
    assert {'not','140','mg'}<=set(query.meaningful_terms)
    assert not intent('ACTIMMUNEX',corpus).product_candidates


def test_multiple_named_products_remain_relevant_without_hard_scope(config, library):
    from amgen_explorer import search
    run, _, corpus, fake = make_searchable(config, library)
    fake.search=lambda *args: []
    result=search.search_library('Tell me about ACTIMMUNE and Repatha',run,config,corpus,client=fake)
    assert {h['product_id'] for h in result.hits}=={'act','repatha'}


def test_generic_ambiguity_returns_catalog_choices_and_preserves_both_sources(config, library):
    from amgen_explorer.query_intent import analyze_query
    from amgen_explorer.models import Product, Corpus
    corpus=Corpus(Path('generic.xml'),'a'*64,[Product('prolia','Prolia','denosumab',[]),Product('xgeva','Xgeva','denosumab',[])],[],[])
    intent=analyze_query('Can you explain denosumab?',corpus)
    assert intent.ambiguity and set(intent.product_candidates)=={'prolia','xgeva'}
    assert set(intent.suggestions)=={'Prolia','Xgeva'}


def test_named_medicine_is_relevance_signal_not_a_hidden_scope(config, library):
    from amgen_explorer.search import search_library
    run,_,corpus,fake=make_searchable(config,library)
    fake.search=lambda *args: []
    result=search_library('ACTIMMUNE latex',run,config,corpus,client=fake)
    assert result.hits[0]['product_id']=='act'
    assert {h['product_id'] for h in result.hits}=={'act','repatha'}


def test_no_literal_overlap_semantic_paraphrase_uses_source_features(config, library):
    from amgen_explorer.search import search_library
    run,records,corpus,fake=make_searchable(config,library)
    original=[]
    def cloud(namespace,query,*args):
        original.append(query)
        return [{**records[1],'_score':.000001}]
    fake.search=cloud
    result=search_library('keep chilled',run,config,corpus,client=fake)
    assert original==['keep chilled']
    assert [h['id'] for h in result.hits]==['chunk-1']
    assert not set('keep chilled'.split()) & set(result.hits[0]['text'].casefold().split())


def test_conversational_pronouns_cannot_anchor_an_unrelated_query(config, library):
    from amgen_explorer.search import analyze_query
    _,_,corpus,_=library
    intent=analyze_query('Who won the football championship?',corpus)
    assert intent.meaningful_terms==['won','football','championship']


def test_named_section_question_does_not_admit_other_products_generic_headings(config, library):
    from amgen_explorer.search import search_library
    run,_,corpus,fake=make_searchable(config,library)
    fake.search=lambda *args: []
    result=search_library('Repatha storage',run,config,corpus,client=fake)
    assert result.hits and {h['product_id'] for h in result.hits}=={'repatha'}


@pytest.mark.parametrize('query',['ACTIMMUNE','ACTIMMUNE warnings'])
def test_genuine_other_product_body_reference_remains_discoverable(library,query):
    from amgen_explorer.query_intent import analyze_query
    from amgen_explorer.search import _relevance
    _,_,corpus,_=library
    intent=analyze_query(query,corpus)
    record={'product_id':'other','source_text':'Warnings about concomitant ACTIMMUNE use.','section_title':'Warnings'}
    assert _relevance(record,intent,None,semantic=True)[0]
    record['source_text']='Warnings about concomitant ACTIMMUNEX use.'
    assert not _relevance(record,intent,None,semantic=True)[0]
