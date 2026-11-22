import copy
import pytest
from amgen_explorer.retrieval import retrieve
from amgen_explorer.indexing import IndexService
from test_indexing import config,plan,FakeDocuments,service
from test_global_search import library


def test_scoped_search_is_pinned_and_provenance_verified(config,plan):
    fake=FakeDocuments(); index=service(config,fake)
    run=index.ingest(plan)
    observed=[]
    original=fake.search
    def search(ns,q,filters,k):
        observed.append((ns,filters))
        return original(ns,q,filters,k)+[{'_id':'invented','product_id':'other'}]
    fake.search=search
    evidence=retrieve('Explain mechanism', 'medicine',run,config,client=fake)
    assert evidence.passages
    assert evidence.namespace==run['namespace'] and evidence.xml_hash==plan.xml_hash
    assert observed[0][1]['$and'][0]=={'product_id':{'$eq':'medicine'}}
    assert any('excluded' in w for w in evidence.warnings)
    assert all(p['metadata']['product_id']=='medicine' for p in evidence.passages)
    assert retrieve('question','other',run,config,client=fake).passages==[]


def test_wrong_cloud_text_is_rejected(config,plan):
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    fake.records[run['namespace']]['chunk-1']['chunk_text']='wrong text'
    fake.records[run['namespace']]['chunk-2']['document_sha256']='wronghash'
    evidence=retrieve('Explain mechanism','medicine',run,config,client=fake)
    assert evidence.passages==[]


def test_variant_requires_document_selection(config,plan):
    plan.chunks[1].metadata['document_id']='variant-b'
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    assert 'Select one' in retrieve('latex','medicine',run,config,client=fake).warnings[0]
    evidence=retrieve('latex','medicine',run,config,document_id='doc',client=fake)
    assert len(evidence.passages)==1
    assert evidence.passages[0]['metadata']['document_id']=='doc'


def test_safety_lookup_adds_canonical_passage_and_budget_never_truncates(config,plan):
    plan.chunks[1].metadata.update(section_title='Warnings and precautions',section_kind='warning')
    plan.chunks[1].text='This is the complete reviewed warning passage with its limitation.'
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    fake.search=lambda *args:[]
    evidence=retrieve('What warnings apply?','medicine',run,config,client=fake)
    assert evidence.passages[0]['text']==plan.chunks[1].text
    config.settings['retrieval']['evidence_token_budget']=5
    assert retrieve('warnings','medicine',run,config,client=fake).passages==[]


def test_long_query_rejected_before_embedding(config,plan):
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    with pytest.raises(ValueError,match='guard'): retrieve('x'*2048,'medicine',run,config,client=fake)

@pytest.mark.parametrize('mutation',['text','namespace','profile','scope','records_path','source_hash','review_pin'])
def test_manifest_integrity_rejected_before_search(config,plan,mutation):
    from amgen_explorer.indexing import atomic_json,read_json
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    path=config.root/run['records_path']
    records=read_json(path)
    if mutation=='text': records[0]['chunk_text']='tampered text'
    if mutation=='source_hash': records[0]['document_sha256']='wrong'
    if mutation=='review_pin': records[0]['review_hash']='wrong'
    if mutation in ('text','source_hash','review_pin'): atomic_json(path,records)
    if mutation=='namespace':run['namespace']='another-namespace'
    if mutation=='profile':config.settings['pinecone']['index_host']='other.svc.example.pinecone.io'
    if mutation=='scope':run['product_ids']=['other-product']
    if mutation=='records_path':run['records_path']='other-place.json'
    calls=[]
    fake.search=lambda *args:calls.append(args)
    with pytest.raises(ValueError):retrieve('mechanism','medicine',run,config,client=fake)
    assert calls==[]


def test_scoped_fallback_accepts_only_verified_local_result_envelopes(config, plan, monkeypatch):
    from types import SimpleNamespace
    from amgen_explorer.connectivity import ProviderError
    from amgen_explorer.indexing import manifest_records
    import amgen_explorer.search as search
    fake = FakeDocuments(); run = service(config, fake).ingest(plan)
    expected = manifest_records(run, config)[0]
    hit = {'id':expected['_id'],'text':expected['chunk_text'],
           'metadata':{k:v for k,v in expected.items() if k not in {'_id','chunk_text'}},
           'run_id':run['run_id'],'namespace':run['namespace'],'xml_hash':run['xml_hash']}
    def unavailable(*args): raise ProviderError('Pinecone',503)
    fake.search = unavailable
    monkeypatch.setattr(search,'search_local',lambda *a,**kw:SimpleNamespace(hits=[hit],warnings=[]),raising=False)
    assert retrieve('Explain mechanism','medicine',run,config,client=fake).passages
    hit['run_id'] = 'other-run'
    assert not retrieve('Explain mechanism','medicine',run,config,client=fake).passages


def test_outage_fallback_rejects_corrupted_artifact_without_second_provider_call(config, library):
    from amgen_explorer.connectivity import ProviderError
    from test_global_search import make_searchable
    run, _, corpus, fake = make_searchable(config, library)
    path = config.root / run['search_artifact']['path']
    path.write_bytes(b'corrupted local artifact')
    calls = []
    def unavailable(*args):
        calls.append(args)
        raise ProviderError('Pinecone',503)
    fake.search = unavailable
    with pytest.raises(ValueError, match='artifact'):
        retrieve('latex','act',run,config,'act-label',client=fake,corpus=corpus)
    assert len(calls) == 1
    assert path.read_bytes() == b'corrupted local artifact'
