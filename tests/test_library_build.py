"""Full-library orchestration uses real PDFs/XML and fake cloud storage."""
import copy
import json
from unittest.mock import patch
import pytest
from amgen_explorer.service import ExplorerService
from amgen_explorer.config import AppConfig, load_config
from amgen_explorer.indexing import IndexService
from amgen_explorer.source_import import SourceUpload
from test_indexing import FakeDocuments
from test_source_import import pdf_bytes

@pytest.fixture
def library_service(tmp_path):
    cfg=AppConfig(copy.deepcopy(load_config(secrets_path=tmp_path/'absent').settings),tmp_path)
    cfg.settings['pinecone']['batch_size']=64
    class FilteredDocuments(FakeDocuments):
        def search(self, namespace, question, filters, top_k):
            rows=list(self.records.get(namespace,{}).values())
            for clause in filters.get('$and',[]):
                for key,predicate in clause.items():
                    if '$eq' in predicate: rows=[r for r in rows if r.get(key)==predicate['$eq']]
                    elif '$in' in predicate: rows=[r for r in rows if r.get(key) in predicate['$in']]
            return rows[:top_k]
    fake=FilteredDocuments()
    class Service(ExplorerService):
        @property
        def index(self): return IndexService(self.config,fake,sleep=lambda _:None,verification_attempts=1)
    service=Service(cfg)
    service.import_documents([SourceUpload('alpha_label.pdf',pdf_bytes()),SourceUpload('beta_label.pdf',pdf_bytes('BETA',text='Latex is described in this source.'))])
    return service,fake


def test_bulk_build_all_sources_without_reviews(library_service):
    service,fake=library_service
    run=service.build_library(service.chunk_config(),activate=True)
    assert run['eligibility_policy']=='bulk_source_verified_v1'
    assert len(run['document_ids'])==2 and len(run['product_ids'])==2
    assert run['search_artifact']['run_id']==run['run_id']
    assert service.active()['run_id']==run['run_id']
    assert not service.config.path('review_database').exists()
    assert all(r.get('review_state')!='accepted' for r in fake.records[run['namespace']].values())


def test_repeat_build_reuses_xml_and_upload(library_service):
    service,fake=library_service
    first=service.build_library(service.chunk_config(),activate=True)
    calls=len(fake.writes)
    again=service.build_library(service.chunk_config(),activate=True)
    assert first['run_id']==again['run_id'] and len(fake.writes)==calls
    assert again.get('previous_run_id')!=again['run_id']


def test_candidate_does_not_activate_and_failed_artifact_keeps_current(library_service):
    service,_=library_service
    first=service.build_library(service.chunk_config(),activate=True)
    with patch('amgen_explorer.search.build_search_artifact',side_effect=ValueError('broken local index')):
        with pytest.raises(ValueError,match='broken local'):
            service.build_library(service.chunk_config(800,80),activate=False)
    assert service.active()['run_id']==first['run_id']
    candidate=service.build_library(service.chunk_config(800,80),activate=False)
    assert service.active()['run_id']==first['run_id']
    assert candidate['document_ids']==first['document_ids']
    service.use_configuration(candidate['run_id'])
    assert service.active()['run_id']==candidate['run_id']
    service.revert_library()
    assert service.active()['run_id']==first['run_id']


def test_missing_registered_source_prevents_rebuild(library_service):
    service,_=library_service
    first=service.build_library(service.chunk_config(),activate=True)
    (service.config.path('source_dir')/'beta_label.pdf').unlink()
    with pytest.raises(ValueError,match='Missing registered'):
        service.build_library(service.chunk_config(),activate=True)
    assert service.active()['run_id']==first['run_id']


def test_library_preview_and_settings_have_no_provider_calls(library_service):
    service,fake=library_service
    plan=service.preview_library(service.chunk_config())
    assert plan.chunks and not fake.writes and fake.checked==0
    assert service.active() is None
    assert service.latest_library_settings().target_tokens==600


def test_run_pinned_search_and_chat_do_not_follow_later_activation(library_service,monkeypatch):
    service,fake=library_service
    first=service.build_library(service.chunk_config(),activate=True)
    monkeypatch.setattr('amgen_explorer.search.DocumentsClient',lambda _:fake)
    result=service.search_library('Latex',run_id=first['run_id'])
    assert result.run_id==first['run_id'] and any(h['metadata']['product_id']=='product-beta' for h in result.hits)
    candidate=service.build_library(service.chunk_config(800,80),activate=True)
    monkeypatch.setattr('amgen_explorer.retrieval.DocumentsClient',lambda _:fake)
    evidence=service._evidence('Latex','product-beta','doc-beta-label',run_id=first['run_id'])
    assert evidence.namespace==first['namespace'] and evidence.namespace!=candidate['namespace']
    assert service.library_corpus(first['run_id']).xml_hash==first['xml_hash']


def test_missing_registered_source_before_initial_build_is_not_forgotten(library_service):
    service,_=library_service
    service.build()
    # Registry already includes both sources; removal cannot shrink the first build.
    (service.config.path('source_dir')/'beta_label.pdf').unlink()
    with pytest.raises(ValueError,match='Missing registered'):
        service.build_library(service.chunk_config(),activate=True)
    assert service.active() is None


def test_current_xml_damage_does_not_hide_valid_published_library(library_service):
    service,_=library_service
    run=service.build_library(service.chunk_config(),activate=True)
    service.config.path('xml_output').write_text('<broken>')
    status=service.library_status()
    assert status['searchable_documents']==2 and status['active']['run_id']==run['run_id']
    assert service.library_corpus(run['run_id']).xml_hash==run['xml_hash']


@pytest.mark.parametrize('field',['text','source_spans','extraction_limitations'])
def test_reexplain_rejects_altered_bulk_evidence(library_service,monkeypatch,field):
    from amgen_explorer.models import TeachingResponse
    service,fake=library_service
    run=service.build_library(service.chunk_config(),activate=True)
    monkeypatch.setattr('amgen_explorer.retrieval.DocumentsClient',lambda _:fake)
    evidence=service._evidence('Storage temperature','product-alpha','doc-alpha-label',run_id=run['run_id'])
    assert evidence.passages
    previous=TeachingResponse('Supported statement',evidence=evidence)
    if field=='text':evidence.passages[0]['text']='Unsupported replacement'
    else:evidence.passages[0]['metadata'][field]='[]'
    # source_spans is nonempty; limitations may be empty, so force a different value.
    if field=='extraction_limitations':evidence.passages[0]['metadata'][field]='["forged"]'
    with pytest.raises(ValueError,match='immutable'):
        service.reexplain('Storage temperature',previous,'Technical detail','product-alpha','doc-alpha-label')
