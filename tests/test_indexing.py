import copy
import json
from pathlib import Path
import pytest
from amgen_explorer.config import load_config
from amgen_explorer.models import Chunk, ChunkPlan
from amgen_explorer.indexing import IndexService, guard_text, atomic_json
from amgen_explorer.connectivity import DocumentsClient, ProviderError

@pytest.fixture
def config(tmp_path):
    cfg = load_config()
    cfg.root = tmp_path
    cfg.settings = copy.deepcopy(cfg.settings)
    cfg.settings['pinecone']['batch_size'] = 1
    cfg.pinecone_api_key = 'test-key'
    cfg.openai_api_key = 'test-key'
    return cfg

@pytest.fixture
def plan():
    def chunk(i):
        return Chunk(f'chunk-{i}', 'This medicine has a reviewed educational source passage.', {
            'product_id':'medicine', 'document_id':'doc', 'document_sha256':'d'*64,
            'section_id':'s1', 'section_title':'Mechanism of action', 'section_kind':'mechanism',
            'page_start':1, 'page_end':1, 'block_ids':[f'block-{i}'], 'filename':'medicine.pdf',
            'review_state':'accepted'}, 65)
    return ChunkPlan([chunk(1), chunk(2)], [], 'f'*64, 'a'*64, 'b'*64, 'c'*64)

class FakeDocuments:
    def __init__(self):
        self.records = {}
        self.writes = []
        self.fail_id = None
        self.transient = 0
        self.hide = False
        self.checked = 0
    def check(self):
        self.checked += 1
        return {'ready':True}
    def upsert(self, namespace, documents):
        self.writes.append([d['_id'] for d in documents])
        if self.transient:
            self.transient -= 1
            raise ProviderError('Pinecone',429)
        if documents[0]['_id'] == self.fail_id:
            raise ProviderError('Pinecone',400)
        self.records.setdefault(namespace,{}).update({d['_id']:copy.deepcopy(d) for d in documents})
        return {'upserted_count':len(documents)}
    def fetch(self, namespace, ids):
        if self.hide: return {}
        return {i:self.records[namespace][i] for i in ids if i in self.records.get(namespace,{})}
    def search(self, namespace, question, filters, top_k):
        if self.hide: return []
        return list(self.records.get(namespace,{}).values())[:top_k]


def service(config, fake):
    return IndexService(config, fake, sleep=lambda _:None, verification_attempts=2)


def test_preview_and_initialization_have_no_side_effects(config,plan):
    index = service(config,FakeDocuments())
    assert index.active() is None
    assert index.runs() == []
    first = index.preview(plan)
    assert first == index.preview(plan)
    assert first['record_count'] == 2
    assert not (config.root/'data').exists()


def test_stage_verify_explicit_publish_and_idempotent_resume(config,plan):
    fake = FakeDocuments(); index = service(config,fake)
    result = index.ingest(plan)
    assert result['status'] == 'verified'
    assert index.active() is None
    assert len(fake.writes)==2
    assert index.ingest(plan)['run_id']==result['run_id']
    assert len(fake.writes)==2
    active = index.activate(result['run_id'],plan)
    assert index.active()['namespace']==active['namespace']
    assert index.runs()[0]['status']=='verified'


def test_interrupted_upload_resumes_completed_batches(config,plan):
    fake=FakeDocuments(); fake.fail_id='chunk-2'; index=service(config,fake)
    with pytest.raises(ProviderError): index.ingest(plan)
    assert index.active() is None
    assert index.runs()[0]['status']=='failed'
    fake.fail_id=None
    result=index.ingest(plan)
    assert result['status']=='verified'
    assert fake.writes.count(['chunk-1'])==1
    assert len(fake.records[result['namespace']])==2


def test_retry_and_failed_consistency_cannot_replace_active(config,plan):
    fake=FakeDocuments(); fake.transient=2; index=service(config,fake)
    first=index.ingest(plan); index.activate(first['run_id'],plan)
    previous=index.active()
    changed=copy.deepcopy(plan); changed.chunks=changed.chunks[:1]; changed.fingerprint='e'*64
    fake.hide=True
    with pytest.raises(ValueError,match='not fully fetchable'): index.ingest(changed)
    assert index.active()==previous
    fake.hide=False
    newer=index.ingest(changed); index.activate(newer['run_id'],changed)
    assert index.active()['namespace']!=previous['namespace']
    assert index.rollback(first['run_id'])['namespace']==previous['namespace']


def test_stale_plan_and_profile_prevent_publish(config,plan):
    fake=FakeDocuments(); index=service(config,fake)
    run=index.ingest(plan)
    changed=copy.deepcopy(plan); changed.review_hash='new'
    with pytest.raises(ValueError,match='changed'): index.activate(run['run_id'],changed)
    with pytest.raises(ValueError,match='current reviewed'): index.activate(run['run_id'])
    config.settings['pinecone']['index_name']='different-index'
    with pytest.raises(ValueError,match='incompatible'): index.rollback(run['run_id'])
    assert index.active() is None


def test_lock_rejects_competing_click(config,plan):
    index=service(config,FakeDocuments())
    with index._lock():
        with pytest.raises(ValueError,match='Another indexing'): index.ingest(plan)


@pytest.mark.parametrize('mutation', ['nested','null','nan','oversized','duplicate','longtext','badpage'])
def test_input_guards_run_before_cloud(config,plan,mutation):
    fake=FakeDocuments(); index=service(config,fake)
    if mutation=='nested': plan.chunks[0].metadata['bad']={'nested':True}
    if mutation=='null': plan.chunks[0].metadata['bad']=None
    if mutation=='nan': plan.chunks[0].metadata['bad']=float('nan')
    if mutation=='oversized': plan.chunks[0].metadata['bad']='a'*41000
    if mutation=='duplicate': plan.chunks.append(plan.chunks[0])
    if mutation=='longtext': plan.chunks[0].text='x'*2041
    if mutation=='badpage': plan.chunks[0].metadata['page_start']=0
    with pytest.raises(ValueError): index.ingest(plan)
    assert fake.checked==0 and fake.writes==[]


def test_actual_documents_rest_shapes(config):
    calls=[]
    def transport(url,payload,**kwargs):
        calls.append((url,payload,kwargs))
        if url.endswith('/fetch'): return {'namespace':'stage','documents':{'c':{'_id':'c'}}}
        if url.endswith('/search'): return {'namespace':'stage','matches':[{'_id':'c'}]}
        return {'upserted_count':1}
    client=DocumentsClient(config,transport=transport)
    assert client.upsert('stage',[{'_id':'c','chunk_text':'source'}])['upserted_count']==1
    assert client.fetch('stage',['c'])=={'c':{'_id':'c'}}
    assert client.search('stage','question',{'product_id':{'$eq':'p'}},5)==[{'_id':'c'}]
    assert '/namespaces/stage/documents/upsert' in calls[0][0]
    assert calls[0][1]=={'documents':[{'_id':'c','chunk_text':'source'}]}
    assert calls[1][1]=={'ids':['c'],'include_fields':['*']}
    assert calls[2][1]['score_by']==[{'type':'embed','fields':['chunk_text'],'query':'question'}]


def test_publication_rejects_changed_manifest_records_before_provider(config,plan):
    from amgen_explorer.indexing import read_json
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    path=config.root/run['records_path'];records=read_json(path)
    records[0]['chunk_text']='Locally changed text with the same record count.'
    atomic_json(path,records)
    checked=fake.checked
    with pytest.raises(ValueError,match='content-hash'):index.activate(run['run_id'],plan)
    assert index.active() is None and fake.checked==checked


def test_idempotent_load_checks_saved_records_integrity(config,plan):
    from amgen_explorer.indexing import read_json
    fake=FakeDocuments(); index=service(config,fake); run=index.ingest(plan)
    path=config.root/run['records_path'];records=read_json(path)
    records[0]['document_id']='other-doc'
    atomic_json(path,records)
    before=len(fake.writes)
    with pytest.raises(ValueError,match='content-hash'):index.ingest(plan)
    assert len(fake.writes)==before
