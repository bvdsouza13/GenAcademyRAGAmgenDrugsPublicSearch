"""Bulk imports preserve the registered collection without passage review."""
import copy
import hashlib
from pathlib import Path
import pytest
import pymupdf
from amgen_explorer.config import AppConfig, load_config
from amgen_explorer.service import ExplorerService
from amgen_explorer.source_import import SourceUpload


def pdf_bytes(brand='ALPHA', text='Storage temperature is controlled.'):
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_text((40,40), f'{brand} (synthetic substance) injection\nInitial U.S. Approval: 2000\nFULL PRESCRIBING INFORMATION\n16 HOW SUPPLIED/STORAGE AND HANDLING\n{text}')
        return doc.tobytes()

@pytest.fixture
def empty_service(tmp_path):
    cfg=load_config(secrets_path=tmp_path/'missing.toml')
    return ExplorerService(AppConfig(copy.deepcopy(cfg.settings),tmp_path))


def test_import_batch_deduplicates_renamed_bytes_and_canonicalizes_title(empty_service):
    data=pdf_bytes()
    result=empty_service.import_documents([SourceUpload('My downloaded label.pdf',data),SourceUpload('second.pdf',data)])
    assert len(result['imported'])==1 and result['duplicates']==['second.pdf']
    assert empty_service.inventory()[0]['filename'].startswith('alpha_')
    registry=empty_service.source_registry()
    assert len(registry['documents'])==1
    assert registry['documents'][0]['product_id']=='product-alpha'


def test_invalid_batch_is_atomic(empty_service):
    with pytest.raises(ValueError,match='PDF'):
        empty_service.import_documents([SourceUpload('alpha.pdf',pdf_bytes()),SourceUpload('broken.pdf',b'not a PDF')])
    assert empty_service.inventory()==[]


def test_import_rejects_traversal_and_unknown_identity(empty_service):
    with pytest.raises(ValueError,match='filename'):
        empty_service.import_documents([SourceUpload('../escape.pdf',pdf_bytes())])
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((40,40),'An unidentifiable source')
        payload=doc.tobytes()
    with pytest.raises(ValueError,match='identity'):
        empty_service.import_documents([SourceUpload('mystery.pdf',payload)])
    assert empty_service.inventory()==[]


def test_replacement_requires_explicit_flag_and_preserves_ids(empty_service):
    first=empty_service.import_documents([SourceUpload('alpha_label.pdf',pdf_bytes())])
    name=first['imported'][0]
    before=empty_service.source_registry()['documents'][0]
    newer=pdf_bytes(text='Updated storage statement.')
    with pytest.raises(ValueError,match='Replace'):
        empty_service.import_documents([SourceUpload(name,newer)])
    empty_service.import_documents([SourceUpload(name,newer,replace_existing=True)])
    after=empty_service.source_registry()['documents'][0]
    assert after['document_id']==before['document_id'] and after['product_id']==before['product_id']
    assert after['sha256']!=before['sha256']
    assert len(list((empty_service.config.root/'data/source-registries').glob('*.json')))>=2


def test_replacement_cannot_change_product_identity(empty_service):
    name=empty_service.import_documents([SourceUpload('alpha_label.pdf',pdf_bytes())])['imported'][0]
    with pytest.raises(ValueError,match='identity'):
        empty_service.import_documents([SourceUpload(name,pdf_bytes('BETA'),replace_existing=True)])


def test_registry_retains_missing_expected_document(empty_service):
    name=empty_service.import_documents([SourceUpload('alpha_label.pdf',pdf_bytes())])['imported'][0]
    (empty_service.config.path('source_dir')/name).unlink()
    assert len(empty_service.source_registry()['documents'])==1
    with pytest.raises(ValueError,match='Missing registered'):
        empty_service.preview_library(empty_service.chunk_config())


def test_reupload_restores_missing_registered_file(empty_service):
    data=pdf_bytes()
    name=empty_service.import_documents([SourceUpload('alpha_label.pdf',data)])['imported'][0]
    before=empty_service.source_registry()['documents'][0]
    (empty_service.config.path('source_dir')/name).unlink()
    result=empty_service.import_documents([SourceUpload('renamed.pdf',data)])
    assert (empty_service.config.path('source_dir')/name).read_bytes()==data
    assert empty_service.source_registry()['documents'][0]==before
    assert result['imported']==[name]


def test_new_variant_reuses_registered_product_id(empty_service):
    from amgen_explorer.source_import import save_registry, _registry
    empty_service.import_documents([SourceUpload('alpha_label.pdf',pdf_bytes())])
    entries=empty_service.source_registry()['documents'];entries[0]['product_id']='medicine-legacy-alpha'
    save_registry(empty_service.config,_registry(entries))
    empty_service.import_documents([SourceUpload('alpha_second.pdf',pdf_bytes(text='Variant body text.'))])
    assert {d['product_id'] for d in empty_service.source_registry()['documents']}=={'medicine-legacy-alpha'}
