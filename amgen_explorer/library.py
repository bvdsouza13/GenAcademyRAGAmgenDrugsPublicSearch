"""Whole-library builds, activation and source/version administration."""
from __future__ import annotations
from .errors import UserFacingError
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

from .chunking import ChunkConfig, prepare_chunks
from .source_import import inspect_inventory, save_registry, library_lock, atomic_bytes
from .service import atomic_json, _read_corpus

BULK_POLICY='bulk_source_verified_v1'


def _prepare(service, chunk_config):
    corpus=service.corpus()
    registry=inspect_inventory(service.config,corpus)
    expected={d['filename']:(d['sha256'],d['document_id'],d['product_id']) for d in registry['documents']}
    current={d.filename:(d.sha256,d.id,d.product_id) for d in corpus.documents} if corpus else {}
    if expected!=current:
        from .extraction import build_corpus
        build_corpus(service.config.path('source_dir'),service.config.path('xml_output'),
                     identities={d['filename']:d for d in registry['documents']})
        _read_corpus.cache_clear();corpus=service.corpus()
    plan=prepare_chunks(corpus,None,chunk_config,policy=BULK_POLICY,source_dir=service.config.path('source_dir'))
    expected_docs=sorted(d['document_id'] for d in registry['documents'])
    expected_products=sorted({d['product_id'] for d in registry['documents']})
    if sorted({c.metadata['document_id'] for c in plan.chunks})!=expected_docs:
        raise UserFacingError('Not every registered document has searchable readable text. Inspect the extraction limitations.')
    if sorted({c.metadata['product_id'] for c in plan.chunks})!=expected_products:
        raise UserFacingError('The full registered medicine inventory was not covered.')
    return corpus,registry,plan


def preview_library(service, chunk_config):
    """Local-only preparation; it may build the single XML but never calls providers."""
    with library_lock(service.config):
        _,_,plan=_prepare(service,chunk_config)
        return plan


def build_library(service, chunk_config, *, activate=True, on_progress=None):
    from .search import build_search_artifact, validate_search_artifact
    from .indexing import manifest_records
    report=on_progress or (lambda _:None)
    with library_lock(service.config):
        backup=service.config.root/'data/migration/pre-bulk-active.json'
        old=service.active()
        if old and not backup.exists(): atomic_json(backup,old)
        config_backup=service.config.root/'data/migration/pre-bulk-settings.json'
        if not config_backup.exists(): atomic_json(config_backup,service.config.settings)
        report({'stage':'Reading documents'})
        corpus,registry,plan=_prepare(service,chunk_config)
        save_registry(service.config,registry)
        report({'stage':'Preparing text','document_count':len(corpus.documents),'record_count':len(plan.chunks),'coverage':plan.coverage})
        service._snapshot(plan)
        def progress(state):
            report({**state,'stage':'Checking search' if state.get('status') in {'verifying','verified'} else 'Uploading'})
        run=service.index.ingest(plan,on_progress=progress)
        records=manifest_records(run,service.config)
        report({'stage':'Checking search','record_count':len(records)})
        artifact=build_search_artifact(run,records,corpus,service.config)
        run.update(search_artifact=asdict(artifact),source_registry_fingerprint=registry['fingerprint'],
                   source_registry=registry,full_library=True,chunk_settings=chunk_config.as_dict(),
                   document_count=len(corpus.documents),product_count=len(corpus.products),
                   page_count=sum(d.page_count for d in corpus.documents),coverage=plan.coverage)
        validate_search_artifact(run,records,service.config,corpus)
        atomic_json(service.config.path('manifest_dir')/(run['run_id']+'.json'),run)
        if activate:
            # Recheck on-disk sources before changing the single active pointer.
            if inspect_inventory(service.config,corpus)['fingerprint']!=registry['fingerprint']:
                raise UserFacingError('Source files changed during the build. Retry before activation.')
            if not old or old['run_id']!=run['run_id']:
                run=service.index.activate(run['run_id'],current_plan=plan)
            else:
                # Idempotent rebuild: retain real rollback history.
                run={**run,**{k:old[k] for k in ('published_at','previous_run_id') if k in old}}
                atomic_json(service.config.path('active_corpus_manifest'),run)
        report({**run,'stage':'Ready' if activate else 'Test library ready'})
        return run


def version(service, run_id=None):
    from .indexing import manifest_records
    if run_id is None:
        run=service.active()
        if run is None:return None
    else:
        if not isinstance(run_id,str) or not re.fullmatch(r'[a-f0-9]{64}',run_id):
            raise UserFacingError('Invalid library version.')
        path=service.config.path('manifest_dir')/(run_id+'.json')
        try: run=json.loads(path.read_text())
        except (OSError,ValueError): raise UserFacingError('This library version is unavailable.') from None
        if run.get('run_id')!=run_id:raise UserFacingError('Library version identity does not match its manifest.')
    if run.get('status')!='verified':raise UserFacingError('This library version has not passed verification.')
    manifest_records(run,service.config)
    return run


def status(service):
    active=service.active()
    try:
        corpus=service.corpus()
    except (ValueError, OSError):
        corpus=service._pinned_corpus(active['xml_hash']) if active else None
    from .source_import import read_registry
    registry=read_registry(service.config,corpus)
    present={row['filename'] for row in service.inventory()}
    missing=[d['filename'] for d in registry['documents'] if d['filename'] not in present]
    return {'missing_sources':missing,'active':active,'source_documents':len(service.inventory()),'source_products':len(corpus.products) if corpus else 0,
            'searchable_documents':len((active or {}).get('document_ids',[])),
            'searchable_products':len((active or {}).get('product_ids',[])),
            'record_count':(active or {}).get('record_count',0),'is_full_library':bool((active or {}).get('full_library')),
            'versions':[r for r in service.index.runs() if r.get('status')=='verified']}


def latest_settings(service):
    active=service.active() or {}
    saved=active.get('chunk_settings',service.config.settings['chunking'])
    return service.chunk_config(saved.get('target_tokens',600),saved.get('overlap_tokens',80))


def use_configuration(service, run_id):
    with library_lock(service.config):
        run=version(service,run_id)
        if not run.get('full_library') or run.get('eligibility_policy')!=BULK_POLICY:
            raise UserFacingError('Choose a verified full-library version. Legacy pilot recovery is separate.')
        registry=inspect_inventory(service.config,service.corpus())
        if registry['fingerprint']!=run.get('source_registry_fingerprint'):
            raise UserFacingError('Source documents changed. Update the full library before applying chunk settings.')
        active=service.active()
        if active and active['run_id']==run_id:return active
        return service.index.rollback(run_id)


def revert_library(service):
    active=service.active() or {}
    previous=active.get('previous_run_id')
    if not previous:raise UserFacingError('There is no previous library version to restore.')
    run=version(service,previous)
    if not run.get('full_library'):
        raise UserFacingError('The previous version is the legacy pilot. Build and test a full library before reverting.')
    with library_lock(service.config):
        return service.index.rollback(previous)
