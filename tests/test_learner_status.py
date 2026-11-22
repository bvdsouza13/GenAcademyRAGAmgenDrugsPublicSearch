"""Learner status skips unused history work without relaxing active-source checks."""
from test_failure_recovery import isolated_library


def test_learner_status_skips_retained_validation_only(isolated_library, monkeypatch):
    from amgen_explorer import library
    service, _, _ = isolated_library
    run = service.build_library(service.chunk_config())
    def unexpected_history(_):
        raise AssertionError('Learner render must not inspect unrelated retained versions')
    monkeypatch.setattr(library, 'list_recoverable_versions', unexpected_history)
    status = service.library_status(include_history=False)
    assert status['active']['run_id'] == run['run_id']
    assert status['versions'] == []
    assert status['history_inspected'] is False


def test_learner_status_still_checks_active_source_bytes(isolated_library):
    service, _, _ = isolated_library
    run = service.build_library(service.chunk_config())
    doc = service.library_corpus(run['run_id']).documents[0]
    pinned = service.config.path('corpus_dir') / run['xml_hash'] / (doc.sha256 + '.pdf')
    pinned.write_bytes(b'corrupt pinned source')
    status = service.library_status(include_history=False)
    assert status['active'] is None
    assert status['is_full_library'] is False
    assert status['warnings']


def test_default_status_keeps_validated_recovery_history(isolated_library):
    service, _, _ = isolated_library
    run = service.build_library(service.chunk_config())
    folder = service.config.path('manifest_dir')
    (folder / ('e' * 64 + '.json')).write_text('{"truncated":')
    status = service.library_status()
    assert status['active']['run_id'] == run['run_id']
    assert [r['run_id'] for r in status['versions']] == [run['run_id']]
    assert status['history_inspected'] is True
    assert len(status['warnings']) == 1
