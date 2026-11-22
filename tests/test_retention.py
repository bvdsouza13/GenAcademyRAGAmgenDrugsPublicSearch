"""Retention stays read-only while durable reference proofs are unavailable."""
import importlib
import json
from pathlib import Path
import tomllib

import pytest

from amgen_explorer.config import AppConfig


@pytest.fixture
def inventory(tmp_path):
    settings = tomllib.loads((Path(__file__).parents[1] / 'config/app.toml').read_text())
    config = AppConfig(settings, tmp_path)
    folder = config.path('manifest_dir')
    folder.mkdir(parents=True)
    xml_hash = 'f' * 64
    snapshot = config.path('corpus_dir') / xml_hash
    snapshot.mkdir(parents=True)
    (snapshot / 'AmgenProducts.xml').write_bytes(b'<shared/>')
    (snapshot / ('e' * 64 + '.pdf')).write_bytes(b'PDF')
    for number, status in ((1, 'verified'), (2, 'verified'), (3, 'failed')):
        run_id = str(number) * 64
        manifest = {'run_id': run_id, 'status': status, 'xml_hash': xml_hash,
                    'namespace': 'pi-' + run_id[:48], 'record_count': number,
                    'created_at': number, 'usage': {'embed_total_tokens': number * 100}}
        (folder / (run_id + '.json')).write_text(json.dumps(manifest))
        (folder / (run_id + '.chunks.json')).write_text('[]')
    active = json.loads((folder / ('1' * 64 + '.json')).read_text())
    active.update(published_at=10, previous_run_id='2' * 64)
    config.path('active_corpus_manifest').write_text(json.dumps(active))
    return config


def api():
    return importlib.import_module('amgen_explorer.retention')


def bytes_on_disk(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_preview_never_mutates_any_files_or_creates_state(inventory):
    before = bytes_on_disk(inventory.root)
    plan = api().plan_cleanup(inventory)
    assert plan.selected_run_ids == ()
    assert bytes_on_disk(inventory.root) == before
    assert plan.cleanup_enabled is False


def test_active_rollback_and_unproven_history_are_retained(inventory):
    plan = api().plan_cleanup(inventory, selected_run_ids=['1' * 64, '2' * 64, '3' * 64])
    runs = {r['run_id']: r for r in plan.runs}
    assert 'active' in runs['1' * 64]['protected_reasons']
    assert 'published' in runs['1' * 64]['protected_reasons']
    assert 'rollback' in runs['2' * 64]['protected_reasons']
    assert all('reference_history_unproven' in r['protected_reasons'] for r in runs.values())
    assert not any(r['cleanup_allowed'] for r in runs.values())


def test_inventory_deduplicates_shared_snapshot_and_exposes_unknown_cost(inventory):
    plan = api().plan_cleanup(inventory)
    assert len(plan.snapshots) == 1
    assert plan.snapshots[0]['local_bytes'] == 12
    assert plan.snapshots[0]['run_ids'] == ['1' * 64, '2' * 64, '3' * 64]
    manifest_bytes = sum(p.stat().st_size for p in inventory.path('manifest_dir').iterdir())
    assert plan.local_bytes == manifest_bytes + 12
    assert plan.last_provider_usage['run_id'] == '3' * 64
    assert plan.last_provider_usage['usage'] == {'embed_total_tokens': 300}
    assert plan.estimated_dollar_cost is None
    assert plan.remote_storage_bytes is None


def test_apply_revalidates_active_reference_changes_and_deletes_nothing(inventory):
    plan = api().plan_cleanup(inventory, selected_run_ids=['3' * 64])
    active_path = inventory.path('active_corpus_manifest')
    active = json.loads(active_path.read_text())
    active['previous_run_id'] = '3' * 64
    active_path.write_text(json.dumps(active))
    before = bytes_on_disk(inventory.root)
    report = api().apply_cleanup(plan)
    assert report.changed_since_preview is True
    assert report.deleted_run_ids == []
    assert 'rollback' in report.retained[0]['protected_reasons']
    assert bytes_on_disk(inventory.root) == before


def test_apply_revalidates_selection_even_if_caller_tampers_with_plan(inventory):
    from dataclasses import replace
    plan = api().plan_cleanup(inventory)
    with pytest.raises(ValueError, match='identifier'):
        api().apply_cleanup(replace(plan, selected_run_ids=('../../outside',)))


def test_repeated_apply_is_idempotent_and_never_constructs_provider(inventory, monkeypatch):
    from amgen_explorer import connectivity
    def unavailable(*args, **kwargs):
        raise AssertionError('retention must not contact a provider')
    monkeypatch.setattr(connectivity, 'DocumentsClient', unavailable)
    plan = api().plan_cleanup(inventory, selected_run_ids=['3' * 64])
    before = bytes_on_disk(inventory.root)
    first = api().apply_cleanup(plan)
    second = api().apply_cleanup(plan)
    assert first == second
    assert first.deleted_run_ids == []
    assert first.retained[0]['run_id'] == '3' * 64
    assert bytes_on_disk(inventory.root) == before


def test_corrupt_manifest_and_missing_selected_run_fail_closed(inventory):
    (inventory.path('manifest_dir') / ('4' * 64 + '.json')).write_text('{')
    plan = api().plan_cleanup(inventory, selected_run_ids=['4' * 64, '5' * 64])
    report = api().apply_cleanup(plan)
    assert report.deleted_run_ids == []
    assert len(report.retained) == 2
    assert 'invalid_manifest' in report.retained[0]['protected_reasons']
    assert 'manifest_unavailable' in report.retained[1]['protected_reasons']


def test_symlinks_are_never_followed_or_counted(inventory, tmp_path):
    outside = tmp_path / 'outside'
    outside.write_bytes(b'sensitive external data')
    (inventory.path('manifest_dir') / ('3' * 64 + '.external')).symlink_to(outside)
    plan = api().plan_cleanup(inventory)
    assert any('symlink' in w.lower() for w in plan.warnings)
    assert all(not r['path'].endswith('.external') for r in plan.files)


def test_malformed_rollback_metadata_cannot_break_fail_closed_inventory(inventory):
    path = inventory.path('manifest_dir') / ('3' * 64 + '.json')
    value = json.loads(path.read_text())
    value['previous_run_id'] = ['untrusted']
    path.write_text(json.dumps(value))
    plan = api().plan_cleanup(inventory, selected_run_ids=['3' * 64])
    assert api().apply_cleanup(plan).deleted_run_ids == []


def test_capacity_runs_real_local_search_and_verified_page_render_without_mutation(tmp_path):
    from test_failure_recovery import isolated_library
    # Invoke the fixture's factory against isolated local providers only.
    service, _, _ = isolated_library.__wrapped__(tmp_path)
    service.build_library(service.chunk_config(), activate=True)
    before = bytes_on_disk(tmp_path)
    capacity = importlib.import_module('scripts.measure_local_capacity')
    report = capacity.measure_capacity(service.config, concurrency=(1, 5), iterations=1,
                                       queries=('storage',))
    assert [r['concurrency'] for r in report['scenarios']] == [1, 5]
    for scenario in report['scenarios']:
        for phase in ('cold', 'warm'):
            assert scenario[phase]['search']['samples'] == scenario['concurrency']
            assert scenario[phase]['page_render']['samples'] == scenario['concurrency']
            assert scenario[phase]['search']['max_ms'] >= 0
            assert scenario[phase]['page_render']['rendered_bytes'] > 0
    assert report['provider_calls'] == 0
    assert report['memory']['peak_process_rss_bytes'] > 0
    assert bytes_on_disk(tmp_path) == before
