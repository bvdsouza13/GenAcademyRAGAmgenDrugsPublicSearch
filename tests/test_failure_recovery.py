"""Isolated recovery fault simulations; production data is never corrupted."""
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


def test_rebuild_of_active_library_detects_missing_remote_records(isolated_library):
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config(), activate=True)
    expected = copy.deepcopy(fake.records[run['namespace']])
    fake.records[run['namespace']].clear()  # Simulate loss outside the application.
    ready = service.build_library(service.chunk_config(), activate=True)
    assert ready['status'] == 'verified'
    assert fake.records[run['namespace']] == expected


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


def test_reupload_of_original_bytes_repairs_corrupt_existing_source(isolated_library):
    service, _, sources = isolated_library
    path = service.config.path('source_dir') / 'alpha_label.pdf'
    path.write_bytes(b'corrupted external replacement')
    service.import_documents([SourceUpload('alpha_label.pdf', sources['alpha_label.pdf'], replace_existing=True)])
    assert path.read_bytes() == sources['alpha_label.pdf']


def test_build_can_regenerate_corrupt_working_xml_from_intact_pdfs(isolated_library):
    service, _, _ = isolated_library
    active = service.build_library(service.chunk_config(), activate=True)
    service.config.path('xml_output').write_text('<broken>')
    assert service.library_status()['active']['run_id'] == active['run_id']
    recovered = service.build_library(service.chunk_config(), activate=True)
    assert recovered['status'] == 'verified'


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

@pytest.mark.parametrize('damage', ['healthy', 'missing', 'metadata', 'all_missing'])
def test_expected_record_verification_and_exact_repair(isolated_library, damage):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    expected = copy.deepcopy(fake.records[run['namespace']])
    target = next(iter(expected))
    if damage == 'missing': del fake.records[run['namespace']][target]
    if damage == 'metadata': fake.records[run['namespace']][target]['section_title'] = 'Changed remotely'
    if damage == 'all_missing': fake.records[run['namespace']].clear()
    before = len(fake.writes)
    result = verify_library(service)
    assert result['outcome'] == ('verified' if damage == 'healthy' else 'drift')
    assert len(fake.writes) == before
    assert result['expected_count'] == len(expected)
    repaired = verify_library(service, repair=True)
    assert repaired['outcome'] == 'verified'
    assert fake.records[run['namespace']] == expected
    written = [i for batch in fake.writes[before:] for i in batch]
    assert written == ([] if damage == 'healthy' else list(expected) if damage == 'all_missing' else [target])
    assert repaired['scope'] == 'expected-record verification; extra remote records are not enumerated'
    assert list((service.config.root/'data/health').glob('*.json'))


def test_health_outage_is_unavailable_and_never_attempts_repair(isolated_library, monkeypatch):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    before = len(fake.writes)
    def outage(*args): raise ProviderError('secret provider payload', 503)
    monkeypatch.setattr(fake, 'fetch', outage)
    result = verify_library(service, repair=True)
    assert result['outcome'] == 'unavailable'
    assert result['missing_count'] == 0 and result['mismatched_count'] == 0
    assert 'secret provider payload' not in json.dumps(result)
    assert len(fake.writes) == before and service.active()['run_id'] == run['run_id']


def test_interrupted_repair_reconciles_remote_state_on_retry(isolated_library, monkeypatch):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    expected = copy.deepcopy(fake.records[run['namespace']])
    fake.records[run['namespace']].clear()
    upsert = fake.upsert
    calls = []
    def interrupt(namespace, rows):
        calls.append(rows[0]['_id'])
        if len(calls) == 2: raise ProviderError('interrupted', 400)
        return upsert(namespace, rows)
    monkeypatch.setattr(fake, 'upsert', interrupt)
    first = verify_library(service, repair=True)
    assert first['outcome'] == 'unavailable'
    assert len(fake.records[run['namespace']]) == 1
    monkeypatch.setattr(fake, 'upsert', upsert)
    before = len(fake.writes)
    assert verify_library(service, repair=True)['outcome'] == 'verified'
    assert fake.records[run['namespace']] == expected
    assert calls[0] not in [i for batch in fake.writes[before:] for i in batch]


def test_health_validates_pinned_assets_before_cloud(isolated_library):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    folder = service.config.path('corpus_dir')/run['xml_hash']
    next(folder.glob('*.pdf')).write_bytes(b'damaged pinned PDF')
    checked = fake.checked
    before = len(fake.writes)
    result = verify_library(service, repair=True)
    assert result['outcome'] == 'local_invalid'
    assert fake.checked == checked and len(fake.writes) == before


def test_concurrent_repair_fails_before_provider(isolated_library):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    service.build_library(service.chunk_config())
    checked = fake.checked
    with library_lock(service.config):
        with pytest.raises(ValueError, match='Another library operation'):
            verify_library(service, repair=True)
    assert fake.checked == checked


@pytest.mark.parametrize('payload', ['[]', 'null', '{"schema_version":1,"documents":null}', '{"broken":'])
def test_invalid_registry_prevents_working_xml_recovery(isolated_library, payload):
    from amgen_explorer.library import recover_working_xml
    service, fake, _ = isolated_library
    # Without an active version there is no trusted inventory to substitute.
    path = service.config.path('xml_output')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'<damaged>')
    (service.config.root/'data/source-registry.json').write_text(payload)
    with pytest.raises(ValueError, match='registry'):
        recover_working_xml(service)
    assert path.read_bytes() == b'<damaged>' and not fake.writes


def test_explicit_working_xml_recovery_quarantines_only_after_valid_build(isolated_library):
    from amgen_explorer.library import recover_working_xml
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    pinned = service.config.path('corpus_dir')/run['xml_hash']/'AmgenProducts.xml'
    original = pinned.read_bytes()
    path = service.config.path('xml_output');path.write_bytes(b'<damaged>')
    before = len(fake.writes)
    report = recover_working_xml(service)
    assert report.schema_valid and service.corpus().documents
    assert pinned.read_bytes() == original
    assert [p.read_bytes() for p in (service.config.root/'data/quarantine').glob('*.xml')] == [b'<damaged>']
    assert len(fake.writes) == before


@pytest.mark.parametrize('payload', ['[]', 'null', '{"run_id":"wrong"}', '{"broken":'])
def test_recoverable_versions_isolate_malformed_history(isolated_library, payload):
    from amgen_explorer.library import list_recoverable_versions
    service, _, _ = isolated_library
    run = service.build_library(service.chunk_config())
    (service.config.path('manifest_dir')/('e'*64+'.json')).write_text(payload)
    result = list_recoverable_versions(service)
    assert [r['run_id'] for r in result['versions']] == [run['run_id']]
    assert len(result['warnings']) == 1


def test_restore_damaged_selected_snapshot_keeps_active(isolated_library):
    from amgen_explorer.library import restore_library_version, list_recoverable_versions
    service, fake, _ = isolated_library
    first = service.build_library(service.chunk_config())
    second = service.build_library(service.chunk_config(800,80))
    (service.config.root/first['records_path']).write_text('[]')
    before = service.config.path('active_corpus_manifest').read_bytes()
    assert [r['run_id'] for r in list_recoverable_versions(service)['versions']] == [second['run_id']]
    with pytest.raises(ValueError): restore_library_version(service, first['run_id'])
    assert service.config.path('active_corpus_manifest').read_bytes() == before


def test_restore_version_rechecks_remote_and_keeps_pointer_on_failure(isolated_library):
    from amgen_explorer.library import restore_library_version
    service, fake, _ = isolated_library
    first = service.build_library(service.chunk_config())
    second = service.build_library(service.chunk_config(800,80))
    fake.records[first['namespace']].clear()
    before = service.config.path('active_corpus_manifest').read_bytes()
    with pytest.raises(ValueError, match='not fully fetchable'):
        restore_library_version(service, first['run_id'])
    assert service.config.path('active_corpus_manifest').read_bytes() == before


def test_recovery_listing_with_no_versions_is_empty(isolated_library):
    from amgen_explorer.library import list_recoverable_versions
    service, fake, _ = isolated_library
    assert list_recoverable_versions(service) == {'versions': [], 'warnings': []}
    assert not fake.checked and not fake.writes


def test_health_search_invisibility_is_drift_without_upsert(isolated_library, monkeypatch):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    service.build_library(service.chunk_config())
    before = len(fake.writes)
    monkeypatch.setattr(fake, 'search', lambda *args: [])
    result = verify_library(service, repair=True)
    assert result['outcome'] == 'drift'
    assert result['matched_count'] == result['expected_count']
    assert not any(result['document_visibility'].values())
    assert len(fake.writes) == before


def test_health_bad_config_never_calls_provider(isolated_library):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    service.build_library(service.chunk_config())
    service.config.settings['pinecone']['index_host'] = 'https://invalid/'
    checked = fake.checked
    result = verify_library(service, repair=True)
    assert result['outcome'] == 'local_invalid' and checked == fake.checked


def test_restoration_explicitly_recovers_damaged_active_pointer(isolated_library):
    from amgen_explorer.library import restore_library_version
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    pointer = service.config.path('active_corpus_manifest')
    pointer.write_bytes(b'{"truncated":')
    assert restore_library_version(service, run['run_id'])['run_id'] == run['run_id']
    assert service.active()['run_id'] == run['run_id']


def test_recoverable_versions_reject_manifest_filename_identity_mismatch(isolated_library):
    from amgen_explorer.library import list_recoverable_versions, restore_library_version
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    impostor = 'e'*64
    (service.config.path('manifest_dir')/(impostor+'.json')).write_text(json.dumps(run))
    result = list_recoverable_versions(service)
    assert [r['run_id'] for r in result['versions']] == [run['run_id']]
    assert len(result['warnings']) == 1
    checked = fake.checked
    with pytest.raises(ValueError, match='identity'):
        restore_library_version(service, impostor)
    assert checked == fake.checked


def test_last_verified_time_survives_subsequent_outage(isolated_library, monkeypatch):
    from amgen_explorer.library_health import verify_library
    service, fake, _ = isolated_library
    service.build_library(service.chunk_config())
    verified = verify_library(service)
    def outage(*args): raise ProviderError('outage', 503)
    monkeypatch.setattr(fake, 'fetch', outage)
    assert verify_library(service)['outcome'] == 'unavailable'
    status = service.library_status()
    assert status['last_verified_at'] == verified['checked_at']
    assert status['health']['outcome'] == 'unavailable'


def test_source_reupload_needs_explicit_replacement_for_corrupt_registered_bytes(isolated_library):
    service, fake, sources = isolated_library
    path = service.config.path('source_dir')/'alpha_label.pdf'
    path.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='Replace'):
        service.import_documents([SourceUpload('alpha_label.pdf', sources['alpha_label.pdf'])])
    assert path.read_bytes() == b'corrupted'


def test_working_recovery_uses_active_pinned_registry_without_guessing(isolated_library):
    from amgen_explorer.library import recover_working_xml
    service, fake, _ = isolated_library
    run = service.build_library(service.chunk_config())
    registry = service.config.root/'data/source-registry.json'
    trusted = registry.read_bytes()
    registry.write_bytes(b'{"damaged":')
    service.config.path('xml_output').write_bytes(b'<broken>')
    recovered = recover_working_xml(service)
    assert recovered.schema_valid and registry.read_bytes() == trusted
    assert service.active()['run_id'] == run['run_id']
    assert b'{"damaged":' in [p.read_bytes() for p in (service.config.root/'data/quarantine').glob('*.registry.json')]


def test_upload_retry_after_exceeding_budget_does_not_sleep_or_repeat(isolated_library, monkeypatch):
    service, fake, _ = isolated_library
    calls = []; sleeps = []
    class RateLimited(ProviderError):
        def __init__(self):
            super().__init__('Pinecone', 429)
            self.retry_after = 10_000
    def fail(*args):
        calls.append(1)
        raise RateLimited()
    monkeypatch.setattr(fake, 'upsert', fail)
    # Direct index keeps its real retry implementation, with a recording sleeper.
    index = IndexService(service.config, fake, sleep=sleeps.append, verification_attempts=1)
    plan = service.preview_library(service.chunk_config())
    with pytest.raises(ProviderError): index.ingest(plan)
    assert len(calls) == 1 and sleeps == []


def test_history_timestamp_shape_is_isolated(isolated_library):
    from amgen_explorer.library import list_recoverable_versions
    service, fake, _ = isolated_library
    first = service.build_library(service.chunk_config())
    second = service.build_library(service.chunk_config(800,80))
    path = service.config.path('manifest_dir')/(first['run_id']+'.json')
    run = json.loads(path.read_text());run['created_at'] = []
    path.write_text(json.dumps(run))
    result = list_recoverable_versions(service)
    assert [r['run_id'] for r in result['versions']] == [second['run_id']]
    assert len(result['warnings']) == 1


def test_preview_damaged_working_xml_does_not_quarantine_or_repair(isolated_library):
    service, fake, _ = isolated_library
    service.build_library(service.chunk_config())
    path = service.config.path('xml_output');path.write_bytes(b'<broken>')
    before = len(fake.writes)
    with pytest.raises(ValueError): service.preview_library(service.chunk_config())
    assert path.read_bytes() == b'<broken>'
    assert not (service.config.root/'data/quarantine').exists()
    assert len(fake.writes) == before


@pytest.mark.parametrize('payload', ['null', '[]', '"scalar"', '{"run_id": "'+'f'*64+'"}'])
def test_active_pointer_invalid_object_types_fail_strictly(isolated_library, payload):
    service, fake, _ = isolated_library
    service.config.path('active_corpus_manifest').write_text(payload)
    with pytest.raises(ValueError): service.active()
    assert service.library_status()['active'] is None
    assert service.library_status()['warnings']


def test_replacement_rejects_source_symlink_before_read_or_write(isolated_library, tmp_path):
    service, fake, _ = isolated_library
    outside = tmp_path/'outside.pdf';outside.write_bytes(pdf_bytes(text='Outside source bytes'))
    path = service.config.path('source_dir')/'alpha_label.pdf'
    path.unlink();path.symlink_to(outside)
    registry = (service.config.root/'data/source-registry.json').read_bytes()
    with pytest.raises(ValueError, match='outside'):
        service.import_documents([SourceUpload('alpha_label.pdf', pdf_bytes(text='Updated registered source'), True)])
    assert path.is_symlink()
    assert (service.config.root/'data/source-registry.json').read_bytes() == registry


@pytest.mark.parametrize('coverage',[[],None,'broken',42])
def test_malformed_active_coverage_is_contained(isolated_library,coverage):
    service,fake,_=isolated_library
    run=service.build_library(service.chunk_config())
    run['coverage']=coverage
    service.config.path('active_corpus_manifest').write_text(json.dumps(run))
    with pytest.raises(ValueError):service.active()
    status=service.library_status()
    assert status['active'] is None and status['warnings']
    assert status['versions']


def test_history_excludes_expected_in_progress_and_legacy_runs_without_corruption_warning(isolated_library):
    service,_,_=isolated_library
    run=service.build_library(service.chunk_config())
    folder=service.config.path('manifest_dir')
    for rid,status,policy in [('a'*64,'indexing','bulk_source_verified_v1'),('b'*64,'verified','manual_review_v1')]:
        (folder/(rid+'.json')).write_text(json.dumps({'run_id':rid,'status':status,'eligibility_policy':policy}))
    result=service.list_recoverable_versions()
    assert [r['run_id'] for r in result['versions']]==[run['run_id']]
    assert not result['warnings']
