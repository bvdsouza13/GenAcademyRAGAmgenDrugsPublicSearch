"""Isolated recovery fault simulations; strict xfails document known gaps.

No production documents, state, credentials or provider are used.  Xfails assert
the desired recovery contract, so an eventual fix must update this assessment.
"""
import copy
import json
from pathlib import Path
import tomllib

import pymupdf
import pytest

from amgen_explorer.config import AppConfig
from amgen_explorer.connectivity import ProviderError
from amgen_explorer.indexing import IndexService
from amgen_explorer.service import ExplorerService
from amgen_explorer.source_import import SourceUpload, library_lock
from test_indexing import FakeDocuments
from test_source_import import pdf_bytes


@pytest.fixture
def isolated_library(tmp_path):
    settings = tomllib.loads((Path(__file__).parents[1] / 'config/app.toml').read_text())
    settings['pinecone']['batch_size'] = 1
    config = AppConfig(settings, tmp_path, 'synthetic-key', 'synthetic-key')

    class FilteredDocuments(FakeDocuments):
        def search(self, namespace, question, filters, top_k):
            rows = list(self.records.get(namespace, {}).values())
            for clause in filters.get('$and', []):
                for key, predicate in clause.items():
                    if '$eq' in predicate:
                        rows = [r for r in rows if r.get(key) == predicate['$eq']]
                    elif '$in' in predicate:
                        rows = [r for r in rows if r.get(key) in predicate['$in']]
            return rows[:top_k]

    fake = FilteredDocuments()

    class Service(ExplorerService):
        @property
        def index(self):
            return IndexService(self.config, fake, sleep=lambda _: None, verification_attempts=1)

    service = Service(config)
    sources = {'alpha_label.pdf': pdf_bytes(),
               'beta_label.pdf': pdf_bytes('BETA', 'A second source describes storage.')}
    service.import_documents([SourceUpload(name, payload) for name, payload in sources.items()])
    return service, fake, sources


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='REC-01: repeat active build trusts historical remote verification')
def test_rebuild_of_active_library_detects_missing_remote_records(isolated_library):
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config(), activate=True)
    expected = copy.deepcopy(fake.records[run['namespace']])
    fake.records[run['namespace']].clear()  # Simulate loss outside the application.
    ready = service.build_library(service.chunk_config(), activate=True)
    assert ready['status'] == 'verified'
    assert fake.records[run['namespace']] == expected


@pytest.mark.xfail(strict=True, raises=ValueError, reason='REC-02: completed batch checkpoints prevent repair after remote loss')
def test_retry_repairs_missing_records_in_verified_candidate(isolated_library):
    service, fake, _ = isolated_library
    baseline = service.build_library(service.chunk_config(), activate=True)
    candidate = service.build_library(service.chunk_config(800, 80), activate=False)
    fake.records[candidate['namespace']].clear()
    with pytest.raises(ValueError, match='not fully fetchable'):
        service.use_configuration(candidate['run_id'])
    assert service.active()['run_id'] == baseline['run_id']
    # A retry should be able to rebuild the lost namespace, but it skips all writes.
    recovered = service.build_library(service.chunk_config(800, 80), activate=True)
    assert recovered['status'] == 'verified'


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='REC-03: duplicate reupload checks existence, not the destination hash')
def test_reupload_of_original_bytes_repairs_corrupt_existing_source(isolated_library):
    service, _, sources = isolated_library
    path = service.config.path('source_dir') / 'alpha_label.pdf'
    path.write_bytes(b'corrupted external replacement')
    service.import_documents([SourceUpload('alpha_label.pdf', sources['alpha_label.pdf'], replace_existing=True)])
    assert path.read_bytes() == sources['alpha_label.pdf']


@pytest.mark.xfail(strict=True, raises=ValueError, reason='REC-04: invalid working XML is parsed before rebuild can regenerate it')
def test_build_can_regenerate_corrupt_working_xml_from_intact_pdfs(isolated_library):
    service, _, _ = isolated_library
    active = service.build_library(service.chunk_config(), activate=True)
    service.config.path('xml_output').write_text('<broken>')
    assert service.library_status()['active']['run_id'] == active['run_id']
    recovered = service.build_library(service.chunk_config(), activate=True)
    assert recovered['status'] == 'verified'


@pytest.mark.xfail(strict=True, raises=json.JSONDecodeError, reason='REC-05: one malformed historical manifest aborts the entire Admin status')
def test_unrelated_corrupt_history_does_not_hide_healthy_active_status(isolated_library):
    service, _, _ = isolated_library
    active = service.build_library(service.chunk_config(), activate=True)
    (service.config.path('manifest_dir') / ('e' * 64 + '.json')).write_text('{"truncated":')
    status = service.library_status()
    assert status['active']['run_id'] == active['run_id']


def test_import_registry_write_failure_restores_sources_and_registry(isolated_library, monkeypatch):
    import amgen_explorer.source_import as imports
    service, _, sources = isolated_library
    before = (service.config.root / 'data/source-registry.json').read_bytes()
    atomic = imports.atomic_bytes
    failed = False

    def fail_once(path, payload):
        nonlocal failed
        if Path(path).name == 'source-registry.json' and not failed:
            failed = True
            raise OSError('Synthetic registry disk failure')
        return atomic(path, payload)

    monkeypatch.setattr(imports, 'atomic_bytes', fail_once)
    with pytest.raises(OSError, match='Synthetic registry'):
        service.import_documents([SourceUpload('alpha_label.pdf', pdf_bytes(text='Updated source.'), True),
                                  SourceUpload('gamma_label.pdf', pdf_bytes('GAMMA'))])
    assert (service.config.path('source_dir') / 'alpha_label.pdf').read_bytes() == sources['alpha_label.pdf']
    assert not (service.config.path('source_dir') / 'gamma_label.pdf').exists()
    assert (service.config.root / 'data/source-registry.json').read_bytes() == before


def test_competing_library_operation_fails_before_any_provider_write(isolated_library):
    service, fake, _ = isolated_library
    with library_lock(service.config):
        with pytest.raises(ValueError, match='Another library operation'):
            service.build_library(service.chunk_config())
    assert fake.checked == 0 and fake.writes == []


def test_source_changed_during_upload_cannot_activate(isolated_library, monkeypatch):
    service, fake, _ = isolated_library
    active = service.build_library(service.chunk_config(), activate=True)
    before = service.config.path('active_corpus_manifest').read_bytes()
    upsert = fake.upsert
    changed = False

    def mutate_source(namespace, rows):
        nonlocal changed
        result = upsert(namespace, rows)
        if not changed:
            changed = True
            (service.config.path('source_dir') / 'alpha_label.pdf').write_bytes(pdf_bytes(text='Changed during upload.'))
        return result

    monkeypatch.setattr(fake, 'upsert', mutate_source)
    with pytest.raises(ValueError, match='changed during the build'):
        service.build_library(service.chunk_config(800, 80), activate=True)
    assert service.active()['run_id'] == active['run_id']
    assert service.config.path('active_corpus_manifest').read_bytes() == before


@pytest.mark.parametrize('status,attempts', [(429, 4), (503, 4), (401, 1)])
def test_bulk_provider_fault_preserves_active_and_retries_are_bounded(isolated_library, monkeypatch, status, attempts):
    service, fake, _ = isolated_library
    service.build_library(service.chunk_config(), activate=True)
    before = service.config.path('active_corpus_manifest').read_bytes()
    calls = []

    def fail(namespace, rows):
        calls.append(namespace)
        raise ProviderError('Synthetic', status)

    monkeypatch.setattr(fake, 'upsert', fail)
    with pytest.raises(ProviderError):
        service.build_library(service.chunk_config(800, 80), activate=True)
    assert len(calls) == attempts
    assert service.config.path('active_corpus_manifest').read_bytes() == before


def test_partial_acknowledgement_retries_unchanged_batch_without_duplicate_ids(isolated_library, monkeypatch):
    service, fake, _ = isolated_library
    upsert = fake.upsert
    partial = True

    def lost_ack(namespace, rows):
        nonlocal partial
        result = upsert(namespace, rows)
        if partial:
            partial = False
            return {'upserted_count': 0}
        return result

    monkeypatch.setattr(fake, 'upsert', lost_ack)
    with pytest.raises(ValueError, match='complete batch'):
        service.build_library(service.chunk_config(), activate=True)
    assert service.active() is None
    recovered = service.build_library(service.chunk_config(), activate=True)
    assert len(fake.records[recovered['namespace']]) == recovered['record_count']
    assert fake.writes[0] == fake.writes[1]


def test_image_only_pdf_rejects_entire_import_batch(isolated_library):
    service, fake, sources = isolated_library
    with pymupdf.open() as doc:
        doc.new_page().draw_rect((10, 10, 200, 200), color=(0, 0, 0), fill=(0.1, 0.1, 0.1))
        unreadable = doc.tobytes()
    before = service.source_registry()
    with pytest.raises(ValueError, match='identity'):
        service.import_documents([SourceUpload('gamma_label.pdf', pdf_bytes('GAMMA')),
                                  SourceUpload('scanned.pdf', unreadable)])
    assert service.source_registry() == before
    assert len(service.inventory()) == len(sources)
    assert fake.writes == []


def test_mixed_pdf_publishes_readable_text_with_unsearchable_page_disclosed_in_coverage(isolated_library):
    service, _, _ = isolated_library
    with pymupdf.open(stream=pdf_bytes('GAMMA'), filetype='pdf') as mixed:
        # A page with visible graphics and no text layer exercises the OCR gap.
        mixed.new_page().draw_rect((10, 10, 200, 200), color=(0, 0, 0), fill=(0.1, 0.1, 0.1))
        payload = mixed.tobytes()
    service.import_documents([SourceUpload('gamma_label.pdf', payload)])
    ready = service.build_library(service.chunk_config(), activate=True)
    assert ready['status'] == 'verified' and ready['coverage']['complete']
    assert ready['coverage']['blank_pages'] == [{'document_id': 'doc-gamma-label', 'page': 2,
                                               'reason': 'blank_or_image_only_ocr_unavailable'}]


def test_missing_source_blocks_build_but_keeps_pinned_search_snapshot(isolated_library):
    service, _, _ = isolated_library
    active = service.build_library(service.chunk_config(), activate=True)
    (service.config.path('source_dir') / 'beta_label.pdf').unlink()
    with pytest.raises(ValueError, match='Missing registered'):
        service.build_library(service.chunk_config())
    assert service.library_status()['missing_sources'] == ['beta_label.pdf']
    assert service.library_corpus(active['run_id']).xml_hash == active['xml_hash']
