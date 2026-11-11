import json
from unittest.mock import Mock
import pytest
from test_library_build import library_service


def custom_suite(service):
    folder=service.config.root/'evals';folder.mkdir(exist_ok=True)
    corpus=service.corpus();block=next(b for b in corpus.blocks if 'Latex' in b.text and b.section_kind=='sourcePageArchive')
    start=block.text.index('Latex');quote='Latex'
    row={'id':'latex','question':'Latex','expected_document_ids':[block.document_id],'xml_hash':corpus.xml_hash,
         'expected_spans':[{'document_id':block.document_id,'document_sha256':block.document_sha256,'page':1,'start':start,'end':start+len(quote)}]}
    (folder/'test.jsonl').write_text(json.dumps(row)+'\n')


def test_compare_pins_sources_and_measures_expected_spans(library_service,monkeypatch):
    service,fake=library_service
    baseline=service.build_library(service.chunk_config(),activate=True)
    custom_suite(service)
    monkeypatch.setattr('amgen_explorer.search.DocumentsClient',lambda _:fake)
    report=service.test_chunk_configuration(service.chunk_config(800,80),'test')
    assert report['baseline_run_id']==baseline['run_id']
    assert service.active()['run_id']==baseline['run_id']
    assert report['candidate']['document_ids']==baseline['document_ids']
    assert report['metrics']['candidate']['quote_coverage']==1
    assert report['metrics']['candidate']['question_count']==2  # Includes automatic coverage of the other document.
    assert report['compatibility_fingerprint'] and report['suite_hash']


def test_same_settings_are_rejected_before_any_paid_call(library_service):
    service,fake=library_service
    service.build_library(service.chunk_config(),activate=True)
    calls=len(fake.writes)
    with pytest.raises(ValueError,match='different'):
        service.test_chunk_configuration(service.chunk_config())
    assert len(fake.writes)==calls


def test_source_changes_reject_experiment_before_candidate_upload(library_service):
    from amgen_explorer.source_import import SourceUpload
    from test_source_import import pdf_bytes
    service,fake=library_service
    service.build_library(service.chunk_config(),activate=True)
    service.import_documents([SourceUpload('gamma.pdf',pdf_bytes('GAMMA'))])
    calls=len(fake.writes)
    with pytest.raises(ValueError,match='Update'):
        service.test_chunk_configuration(service.chunk_config(800,80))
    assert len(fake.writes)==calls


def test_mismatched_suite_source_rejects_before_search(library_service):
    service,_=library_service
    a=service.build_library(service.chunk_config(),activate=True)
    b=service.build_library(service.chunk_config(800,80),activate=False)
    custom_suite(service)
    path=service.config.root/'evals/test.jsonl'
    row=json.loads(path.read_text());row['xml_hash']='bad';path.write_text(json.dumps(row)+'\n')
    service.search_library=Mock(side_effect=AssertionError('paid call'))
    with pytest.raises(ValueError,match='suite'):
        service.evaluate_versions(a['run_id'],b['run_id'],'test')
    service.search_library.assert_not_called()


def test_suite_rebinds_unchanged_sources_after_full_library_addition(library_service,monkeypatch):
    from amgen_explorer.source_import import SourceUpload
    from test_source_import import pdf_bytes
    service,fake=library_service
    service.build_library(service.chunk_config(),activate=True)
    custom_suite(service)
    service.import_documents([SourceUpload('gamma_label.pdf',pdf_bytes('GAMMA'))])
    baseline=service.build_library(service.chunk_config(),activate=True)
    monkeypatch.setattr('amgen_explorer.search.DocumentsClient',lambda _:fake)
    report=service.test_chunk_configuration(service.chunk_config(800,80),'test')
    assert report['controls']['xml_hash']==baseline['xml_hash']
    assert report['metrics']['baseline']['question_count']>=3
    assert any(row['expected_document_ids']==['doc-gamma-label'] for row in report['rows'])


def test_changed_expected_quote_is_visible_and_stays_in_score_denominator(library_service,monkeypatch):
    from amgen_explorer.source_import import SourceUpload
    from test_source_import import pdf_bytes
    service,fake=library_service
    service.build_library(service.chunk_config(),activate=True)
    custom_suite(service)
    service.import_documents([SourceUpload('beta_label.pdf',pdf_bytes('BETA',text='Revised source without the expected phrase.'),replace_existing=True)])
    service.build_library(service.chunk_config(),activate=True)
    monkeypatch.setattr('amgen_explorer.search.DocumentsClient',lambda _:fake)
    report=service.test_chunk_configuration(service.chunk_config(800,80),'test')
    expected=next(row for row in report['rows'] if row['id']=='latex')
    assert expected['baseline']['quote_coverage']==0 and expected['candidate']['quote_coverage']==0
    assert any('unavailable expected' in warning.lower() for warning in report['warnings'])
