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


def _prepare(service, chunk_config, *, recover=False, reextract=False):
    try:
        corpus=service.corpus()
    except (ValueError, OSError):
        if not recover:
            raise UserFacingError('The working XML is damaged. Recover it or explicitly build the library again.') from None
        _recover_working_xml(service)
        corpus=service.corpus()
    registry=inspect_inventory(service.config,corpus)
    expected={d['filename']:(d['sha256'],d['document_id'],d['product_id']) for d in registry['documents']}
    current={d.filename:(d.sha256,d.id,d.product_id) for d in corpus.documents} if corpus else {}
    from .extraction import PARSER_VERSION, LAYOUT_POLICY_VERSION, x
    parser_changed=bool(corpus and any(b.parser_version!=PARSER_VERSION for b in corpus.blocks))
    policy_changed=False
    if reextract and corpus:
        import xml.etree.ElementTree as ET
        policy_changed=ET.parse(corpus.xml_path).getroot().get(x('layoutPolicyVersion'))!=LAYOUT_POLICY_VERSION
    if expected!=current or (reextract and (parser_changed or policy_changed)):
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
        corpus,registry,plan=_prepare(service,chunk_config,recover=True,reextract=True)
        save_registry(service.config,registry)
        from .durable_library import backend_enabled, sync_paths
        if backend_enabled():
            sync_paths(service.config, [
                service.config.path('xml_output'),
                service.config.root/'data/source-registry.json',
                service.config.root/'data/source-registries'/(registry['fingerprint']+'.json'),
            ])
        report({'stage':'Preparing text','document_count':len(corpus.documents),'record_count':len(plan.chunks),'coverage':plan.coverage})
        service._snapshot(plan)
        def progress(state):
            report({**state,'stage':'Checking search' if state.get('status') in {'verifying','verified'} else 'Uploading'})
        run=service.index.ingest(plan,on_progress=progress)
        records=manifest_records(run,service.config)
        report({'stage':'Checking search','record_count':len(records)})
        artifact=build_search_artifact(run,records,corpus,service.config)
        from .coverage import coverage_summary
        run.update(search_artifact=asdict(artifact),source_registry_fingerprint=registry['fingerprint'],
                   source_registry=registry,full_library=True,chunk_settings=chunk_config.as_dict(),
                   document_count=len(corpus.documents),product_count=len(corpus.products),
                   page_count=sum(d.page_count for d in corpus.documents),coverage=plan.coverage,page_coverage=coverage_summary(corpus))
        validate_search_artifact(run,records,service.config,corpus)
        atomic_json(service.config.path('manifest_dir')/(run['run_id']+'.json'),run)
        if backend_enabled():
            sync_paths(service.config, [
                service.config.path('manifest_dir')/(run['run_id']+'.json'),
                service.config.root/run['search_artifact']['path'],
            ])
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
        if not isinstance(run,dict) or run.get('run_id')!=run_id:raise UserFacingError('Library version identity does not match its manifest.')
    if not isinstance(run,dict):raise UserFacingError('This library version is unavailable.')
    if run.get('status')!='verified':raise UserFacingError('This library version has not passed verification.')
    manifest_records(run,service.config)
    return run


def status(service, *, include_history=True):
    from .source_import import read_registry
    from .library_health import latest_report
    warnings = []
    try:
        active = service.active()
        if active:
            version(service)
            from .library_health import validate_local_run
            if active.get('full_library'): validate_local_run(service.config, active)
    except (OSError, ValueError, KeyError, TypeError):
        active = None
        warnings.append('The active library is damaged. Restore a validated retained version in Recovery.')
    try:
        corpus = service.corpus()
    except (ValueError, OSError):
        corpus = None
        warnings.append('The working XML is unavailable. Recover it from the registered source PDFs.')
    if corpus is None and active:
        try: corpus = service._pinned_corpus(active['xml_hash'])
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append('The active XML snapshot is unavailable.')
    try:
        registry = read_registry(service.config, corpus)
    except (OSError, ValueError, KeyError, TypeError):
        registry = {'documents': []}
        warnings.append('The source registry failed validation. Recover it before rebuilding.')
    try: inventory = service.inventory()
    except OSError:
        inventory = []
        warnings.append('The source directory is unavailable.')
    present = {row['filename'] for row in inventory}
    missing = [d['filename'] for d in registry['documents'] if d['filename'] not in present]
    # Learner pages do not display retained versions. Keep active source checks
    # above on every render; inspect all retained assets only where requested.
    retained = list_recoverable_versions(service) if include_history else {'versions': [], 'warnings': []}
    warnings.extend(retained['warnings'])
    health = latest_report(service.config, (active or {}).get('run_id')) if active else None
    verified = latest_report(service.config, active['run_id'], outcome='verified') if active else None
    last_verified = verified['checked_at'] if verified else (active or {}).get('verified_at')
    return {'missing_sources':missing,'active':active,'source_documents':len(inventory),
            'source_products':len(corpus.products) if corpus else 0,
            'searchable_documents':len((active or {}).get('document_ids',[])),
            'searchable_products':len((active or {}).get('product_ids',[])),
            'record_count':(active or {}).get('record_count',0),'is_full_library':bool((active or {}).get('full_library')),
            'versions':retained['versions'], 'history_inspected':include_history, 'warnings':warnings, 'health':health, 'latest_verification':health,
            'last_verified_at':last_verified}


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


def list_recoverable_versions(service):
    """Validate each retained entry independently, locally, without repairing it."""
    from .library_health import validate_local_run
    result = []; warnings = []
    folder = service.config.path('manifest_dir')
    if folder.exists():
        for path in sorted(folder.glob('*.json')):
            if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name): continue
            try:
                raw=json.loads(path.read_text())
                if not isinstance(raw,dict) or raw.get('run_id')!=path.stem:
                    raise ValueError('Retained manifest identity mismatch.')
                # In-progress candidates and legacy pilot versions are not
                # full-library recovery choices. Their presence is expected.
                if raw.get('status') in {'indexing','verifying','failed'}:
                    continue
                if raw.get('status')=='verified' and raw.get('eligibility_policy','manual_review_v1')!='bulk_source_verified_v1':
                    continue
                run = version(service, path.stem)
                validate_local_run(service.config, run)
                result.append(run)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                warnings.append('A retained library version failed local validation: '+path.stem[:12]+'.')
    return {'versions':sorted(result, key=lambda r:r.get('created_at',0), reverse=True), 'warnings':warnings}


def restore_library_version(service, run_id):
    from .library_health import validate_local_run
    with library_lock(service.config):
        run = version(service, run_id)
        validate_local_run(service.config, run)
        # _publish repeats remote verification under the index lock and replaces
        # the active pointer only after every readiness check succeeds.
        return service.index._publish(run_id, allow_damaged_active=True)


def _recover_working_xml(service):
    """Caller owns library lock. Regenerate only from a trusted complete registry."""
    import tempfile
    from .source_import import read_registry, validate_registry
    from .extraction import build_corpus
    from .xml_store import load_corpus
    path = service.config.path('xml_output')
    registry_path = service.config.root/'data/source-registry.json'
    registry = None
    if registry_path.exists():
        try: registry = read_registry(service.config)
        except ValueError: pass
    if registry is None:
        # A retained manifest binds a complete inventory; an arbitrary snapshot
        # filename or a scan of remaining PDFs cannot establish that inventory.
        try:
            from .library_health import validate_local_run
            active = version(service)
            validate_local_run(service.config, active)
            registry = validate_registry(active['source_registry'])
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            raise UserFacingError('No trusted complete source registry is available for recovery.') from None
    if not registry['documents']:
        raise UserFacingError('No trusted complete source registry is available for recovery.')
    directory = service.config.path('source_dir')
    expected = {d['filename']:d for d in registry['documents']}
    names = {p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower()=='.pdf'} if directory.exists() else set()
    if names != set(expected):
        raise UserFacingError('Source registry and source PDFs do not match. Restore the complete registered collection before recovery.')
    for name, document in expected.items():
        source = directory/name
        if (not source.resolve().is_relative_to(directory.resolve())
                or hashlib.sha256(source.read_bytes()).hexdigest() != document['sha256']):
            raise UserFacingError('A registered source PDF is missing or changed. Restore its registered bytes before recovery.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.recovery-', dir=path.parent) as temporary:
        candidate = Path(temporary)/path.name
        report = build_corpus(directory, candidate, identities=expected)
        corpus = load_corpus(candidate)
        if {d.id:(d.product_id,Path(d.filename).name,d.sha256) for d in corpus.documents} != {
                d['document_id']:(d['product_id'],d['filename'],d['sha256']) for d in registry['documents']}:
            raise UserFacingError('Recovered XML did not preserve the registered inventory.')
        # Preserve damaged bytes only during this explicit operation, after all
        # recovery inputs and the replacement XML have passed validation.
        if path.exists():
            damaged = path.read_bytes()
            quarantine = service.config.root/'data/quarantine'/(hashlib.sha256(damaged).hexdigest()+'.xml')
            atomic_bytes(quarantine, damaged)
            report.snapshot_path = str(quarantine)
        atomic_bytes(path, candidate.read_bytes())
        if candidate.with_suffix('.report.json').exists():
            atomic_bytes(path.with_suffix('.report.json'), candidate.with_suffix('.report.json').read_bytes())
        report.output_path = str(path)
    if not registry_path.exists() or registry_path.read_bytes() != (json.dumps(registry,ensure_ascii=False,indent=2)+'\n').encode():
        if registry_path.exists():
            damaged = registry_path.read_bytes()
            atomic_bytes(service.config.root/'data/quarantine'/(hashlib.sha256(damaged).hexdigest()+'.registry.json'), damaged)
        save_registry(service.config,registry)
    _read_corpus.cache_clear()
    from .durable_library import backend_enabled, sync_paths
    if backend_enabled():
        sync_paths(service.config)
    return report


def recover_working_xml(service):
    with library_lock(service.config):
        return _recover_working_xml(service)
