"""Explicit expected-record verification and conservative repair of retained runs."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import time
import uuid

from .eligibility import BULK_POLICY, policy_for, validate_record_sources
from .indexing import atomic_json, manifest_records, read_json
from .source_import import library_lock, validate_registry

SCOPE = 'expected-record verification; extra remote records are not enumerated'


def validate_local_run(config, run):
    """Fail before provider access unless every pinned local repair input is intact."""
    from .search import validate_search_artifact
    from .xml_store import load_corpus
    errors = config.validate()
    if errors:
        raise ValueError('The library configuration is invalid.')
    records = manifest_records(run, config)
    for field in ('created_at', 'verified_at'):
        value = run.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('The library manifest contains an invalid timestamp.')
    if policy_for(run) != BULK_POLICY or not run.get('full_library'):
        raise ValueError('Choose a retained full-library version.')
    xml_hash = run.get('xml_hash')
    if not isinstance(xml_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', xml_hash):
        raise ValueError('The pinned XML identity is invalid.')
    folder = config.path('corpus_dir')/xml_hash
    path = folder/'AmgenProducts.xml'
    if hashlib.sha256(path.read_bytes()).hexdigest() != xml_hash:
        raise ValueError('The pinned XML snapshot is unavailable or changed.')
    corpus = load_corpus(path)
    if corpus.xml_hash != xml_hash:
        raise ValueError('The pinned XML snapshot identity changed.')
    registry = validate_registry(run.get('source_registry'))
    if run.get('source_registry_fingerprint') != registry['fingerprint']:
        raise ValueError('The pinned source registry identity changed.')
    registered = {d['document_id']: (d['product_id'], d['filename'], d['sha256']) for d in registry['documents']}
    if registered != {d.id:(d.product_id, Path(d.filename).name, d.sha256) for d in corpus.documents}:
        raise ValueError('The pinned source inventory does not match the XML snapshot.')
    for document in corpus.documents:
        source = folder/(document.sha256+'.pdf')
        if not source.resolve().is_relative_to(folder.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != document.sha256:
            raise ValueError('A pinned PDF snapshot is unavailable or changed.')
    validate_record_sources(records, corpus, run, config.settings['pinecone']['text_field'])
    validate_search_artifact(run, records, config, corpus)
    return records, corpus


def observation_report(run, observation):
    clean = {key: observation[key] for key in ('expected_count', 'matched_count', 'missing_count', 'mismatched_count', 'document_visibility')}
    verified = not clean['missing_count'] and not clean['mismatched_count'] and all(clean['document_visibility'].values())
    return {'run_id': run['run_id'], 'checked_at': time.time(), 'scope': SCOPE,
            'outcome': 'verified' if verified else 'drift', 'errors': [], **clean}


def save_report(config, report):
    folder = config.root/'data/health'
    atomic_json(folder/(str(time.time_ns())+'-'+uuid.uuid4().hex+'.json'), report)
    return report


def latest_report(config, run_id=None, *, outcome=None):
    """Local status read only. Corrupt reports do not erase older healthy history."""
    folder = config.root/'data/health'
    reports = []
    if folder.exists():
        for path in folder.glob('*.json'):
            try:
                report = read_json(path)
                if (isinstance(report, dict) and report.get('outcome') in {'verified','drift','unavailable','local_invalid'}
                        and isinstance(report.get('checked_at'), (int, float))
                        and (run_id is None or report.get('run_id') == run_id)
                        and (outcome is None or report.get('outcome') == outcome)):
                    reports.append(report)
            except (OSError, ValueError, TypeError):
                continue
    return max(reports, key=lambda report: report['checked_at'], default=None)


def verify_library(service, run_id=None, *, repair=False, on_progress=None):
    """No inventory listing/deletion; repair identical pinned records only on request."""
    from .library import version
    progress = on_progress or (lambda _: None)
    # The library lock always precedes the index lock, as for Build and Restore.
    with library_lock(service.config):
        report = {'run_id': run_id, 'checked_at': time.time(), 'scope': SCOPE,
                  'outcome': 'local_invalid', 'expected_count': 0, 'matched_count': 0,
                  'missing_count': 0, 'mismatched_count': 0, 'document_visibility': {}, 'errors': []}
        try:
            run = version(service, run_id)
            if run is None:
                raise ValueError('No active library.')
            report['run_id'] = run['run_id']
            records, _ = validate_local_run(service.config, run)
            report['expected_count'] = len(records)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            report['errors'] = ['Pinned local library assets or configuration failed validation. Restore an intact retained version.']
            return save_report(service.config, report)
        index = service.index
        with index._lock() as db:
            repair_usage = None
            try:
                progress({'run_id': run['run_id'], 'status': 'verifying'})
                index.client.check()
                observation = index._observe(run, records)
                report = observation_report(run, observation)
                if repair and report['outcome'] == 'drift':
                    progress({'run_id': run['run_id'], 'status': 'repairing'})
                    from .repair_accounting import repair_accounting
                    with repair_accounting(service.config, run) as (working, repair_usage, checkpoint):
                        observation = index._repair(working, records, db, on_progress=progress,
                                                    require_verified=False, on_usage=checkpoint)
                    report = observation_report(run, observation)
                    report['repair_usage'] = repair_usage
                return save_report(service.config, report)
            except Exception:
                # A failed request does not establish record absence. Never include
                # provider exception text or raw responses in durable reports.
                report.update(outcome='unavailable', checked_at=time.time(), missing_count=0, mismatched_count=0,
                              matched_count=0, document_visibility={},
                              errors=['Remote library verification is unavailable. Check connectivity and retry.'])
                if repair_usage is not None:
                    report['repair_usage'] = repair_usage
                return save_report(service.config, report)
