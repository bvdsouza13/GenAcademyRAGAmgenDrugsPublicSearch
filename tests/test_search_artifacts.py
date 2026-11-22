"""Run-bound artifacts fail closed on tampering and survive other versions."""
from dataclasses import asdict
import copy
import sqlite3

import pytest

from amgen_explorer.indexing import atomic_json
from test_global_search import config, plan, library, make_searchable


def test_artifact_is_immutable_and_idempotent(config, library):
    from amgen_explorer.search import build_search_artifact, validate_search_artifact
    run, records, corpus, _ = make_searchable(config, library)
    artifact = run['search_artifact']
    path = config.root / artifact['path']
    stamp = path.stat().st_mtime_ns
    second = build_search_artifact(run, records, corpus, config)
    assert asdict(second) == artifact and path.stat().st_mtime_ns == stamp
    assert validate_search_artifact(run, records, config, corpus).run_id == run['run_id']
    assert artifact['engine'] in {'fts5','fallback'}
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM records').fetchone()[0] == 4


@pytest.mark.parametrize('mutation', ['record_text','artifact_bytes','artifact_path','artifact_run','artifact_version','corpus_hash','document_hash','names','missing'])
def test_invalid_artifact_fails_before_cloud_and_never_rebuilds_silently(config, library, mutation):
    from amgen_explorer.search import search_library
    run, records, corpus, fake = make_searchable(config, library)
    path = config.root / run['search_artifact']['path']
    if mutation == 'record_text':
        records[0]['source_text'] = 'changed'
        atomic_json(config.root / run['records_path'], records)
    if mutation == 'artifact_bytes':
        with sqlite3.connect(path) as db:
            db.execute("UPDATE records SET source_text='changed'")
    if mutation == 'artifact_path': run['search_artifact']['path'] = '../outside.sqlite'
    if mutation == 'artifact_run': run['search_artifact']['run_id'] = 'e'*64
    if mutation == 'artifact_version': run['search_artifact']['ranking_version'] = 'unknown'
    if mutation == 'corpus_hash': corpus.xml_hash = 'e'*64
    if mutation == 'document_hash': corpus.documents[0].sha256 = 'e'*64
    if mutation == 'names': corpus.products[0].name = 'Wrong brand'
    if mutation == 'missing': path.unlink()
    def forbidden(*args):
        raise AssertionError('Provider called before local validation')
    fake.search = forbidden
    with pytest.raises(ValueError):
        search_library('latex', run, config, corpus, client=fake)
    if mutation == 'missing': assert not path.exists()


def test_changed_manifest_digest_cannot_bless_modified_record_payload(config, library):
    from amgen_explorer.search import search_library
    import hashlib
    run, records, corpus, fake = make_searchable(config, library)
    path = config.root / run['search_artifact']['path']
    with sqlite3.connect(path) as db:
        db.execute("UPDATE records SET source_text='invented'")
    run['search_artifact']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='artifact'):
        search_library('latex', run, config, corpus, client=fake)


def test_retained_run_remains_searchable_after_new_artifact_and_rollback(config, library):
    from amgen_explorer.search import build_search_artifact, search_library
    from amgen_explorer.indexing import digest, index_profile, manifest_records
    run, records, corpus, fake = make_searchable(config, library)
    old = copy.deepcopy(run)
    updated = copy.deepcopy(run)
    updated['fingerprint'] = 'e'*64
    updated['run_id'] = digest({'plan':updated['fingerprint'],'records':records,'profile':index_profile(config)})
    updated['namespace'] = updated['profile']['namespace_prefix']+'-'+updated['run_id'][:48]
    updated['records_path'] = str((config.path('manifest_dir')/(updated['run_id']+'.chunks.json')).relative_to(config.root))
    atomic_json(config.root / updated['records_path'], records)
    updated.pop('search_artifact')
    updated['search_artifact'] = asdict(build_search_artifact(updated, records, corpus, config))
    fake.search = lambda *args: []
    latest = search_library('latex', updated, config, corpus, client=fake)
    retained = search_library('latex', old, config, corpus, client=fake)
    rolled_back = search_library('latex', old, config, corpus, client=fake)
    assert latest.run_id != retained.run_id
    assert [h['id'] for h in retained.hits] == [h['id'] for h in rolled_back.hits]
    assert all(h['run_id']==old['run_id'] and h['metadata']['document_sha256'] in {'0'*64,'2'*64} for h in retained.hits)
    assert updated['search_artifact']['path'] != old['search_artifact']['path']


def test_rebuild_cannot_refresh_checksum_of_previously_pinned_artifact(config, library):
    from amgen_explorer.search import build_search_artifact
    run, records, corpus, _ = make_searchable(config, library)
    path = config.root / run['search_artifact']['path']
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=7')
    with pytest.raises(ValueError, match='artifact'):
        build_search_artifact(run, records, corpus, config)


def test_runtime_ranking_upgrade_retains_v1_artifact_identity_and_never_upserts(config, library):
    from amgen_explorer.search import RANKING_VERSION, search_library
    run, _, corpus, fake=make_searchable(config,library)
    descriptor=copy.deepcopy(run['search_artifact'])
    path=config.root/descriptor['path'];payload=path.read_bytes();stamp=path.stat().st_mtime_ns
    writes=copy.deepcopy(fake.writes)
    fake.search=lambda *args: []
    result=search_library('What is ACTIMMUNE?',run,config,corpus,client=fake)
    assert descriptor['ranking_version']=='global-rrf-v1'
    assert result.ranking_version==RANKING_VERSION!='global-rrf-v1'
    assert path.read_bytes()==payload and path.stat().st_mtime_ns==stamp
    assert run['search_artifact']==descriptor and fake.writes==writes
