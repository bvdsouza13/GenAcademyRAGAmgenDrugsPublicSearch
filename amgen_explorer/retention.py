"""Read-only retention inventory; cleanup fails closed without reference proofs.

Publication is recorded on the active pointer, not durably on every manifest,
and live conversation references exist only in process memory. Neither an old
``verified`` status nor a missing ``published_at`` proves a run unreferenced.
Consequently this module deliberately has no provider/deletion adapter.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re

from .config import AppConfig

_RUN_ID = re.compile(r'[a-f0-9]{64}')
_PROOF_GAP = ('Cleanup disabled: historical publications and current conversation '
              'references are not durably recorded; no retained run is proven unreferenced.')


@dataclass(frozen=True)
class CleanupPlan:
    selected_run_ids: tuple[str, ...]
    runs: list[dict]
    snapshots: list[dict]
    files: list[dict]
    local_bytes: int
    fingerprint: str
    warnings: list[str]
    last_provider_usage: dict | None
    cleanup_enabled: bool = False
    remote_storage_bytes: int | None = None
    estimated_dollar_cost: float | None = None
    _config: AppConfig = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class CleanupReport:
    selected_run_ids: tuple[str, ...]
    deleted_run_ids: list[str]
    retained: list[dict]
    changed_since_preview: bool
    warnings: list[str]
    cleanup_enabled: bool = False


def _selected(values):
    if isinstance(values, (str, bytes)):
        raise ValueError('Selected run identifiers must be a sequence of run IDs.')
    result = []
    for value in values:
        if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
            raise ValueError('Invalid selected run identifier.')
        if value not in result:
            result.append(value)
    return tuple(result)


def _json(path):
    try:
        value = json.loads(path.read_bytes())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def plan_cleanup(config, *, selected_run_ids=()):
    """Inventory local bytes and known references without writes or provider calls.

    ``local_bytes`` counts unique regular files in manifest/corpus directories;
    per-run ``shared_snapshot_bytes`` must not be summed across runs. Sources,
    working XML, databases, reports and remote storage are outside this total.
    Selection expresses intent only: it is never deletion authorization/proof.
    """
    selected = _selected(selected_run_ids)
    warnings = [_PROOF_GAP]
    files = []
    signatures = []
    root = config.root.resolve()

    def label(path):
        return str(path.relative_to(root))

    def scan(path):
        if path.is_symlink():
            warnings.append('Skipped symlink: ' + label(path))
            signatures.append((label(path), 'symlink'))
            return
        if not path.exists():
            signatures.append((label(path), 'missing'))
            return
        if path.is_dir():
            try:
                children = sorted(path.iterdir())
            except OSError:
                warnings.append('Unable to inventory local directory: ' + label(path))
                signatures.append((label(path), 'unreadable'))
                return
            for child in children:
                scan(child)
        elif path.is_file():
            try:
                payload = path.read_bytes()
                sha = hashlib.sha256(payload).hexdigest()
                files.append({'path': label(path), 'local_bytes': len(payload), 'sha256': sha})
                signatures.append((label(path), sha))
            except OSError:
                warnings.append('Unable to inventory local file: ' + label(path))
                signatures.append((label(path), 'unreadable'))

    manifests = config.path('manifest_dir')
    corpora = config.path('corpus_dir')
    scan(manifests)
    scan(corpora)
    # The current pointer and migration backup are durable known references;
    # manifests can additionally carry rollback links or publication metadata.
    references = []
    for path in (config.path('active_corpus_manifest'), root / 'data/migration/pre-bulk-active.json'):
        if path.is_symlink():
            warnings.append('Skipped reference symlink: ' + label(path))
            signatures.append((label(path), 'symlink'))
            continue
        try:
            payload = path.read_bytes()
            signatures.append((label(path), hashlib.sha256(payload).hexdigest()))
        except OSError:
            signatures.append((label(path), 'missing_or_unreadable'))
            continue
        value = _json(path)
        if value is None:
            warnings.append('A durable reference could not be read: ' + label(path))
        else:
            references.append((path == config.path('active_corpus_manifest'), value))

    runs = []
    manifest_prefix = label(manifests) + '/'
    for entry in files:
        name = Path(entry['path']).name
        if (str(Path(entry['path']).parent) != label(manifests)
                or not name.endswith('.json') or not _RUN_ID.fullmatch(name[:-5])):
            continue
        run_id = name[:-5]
        manifest = _json(root / entry['path'])
        valid = manifest is not None and manifest.get('run_id') == run_id
        value = manifest if valid else {}
        reasons = ['reference_history_unproven']
        if not valid:
            reasons.append('invalid_manifest')
        if value.get('published_at') is not None:
            reasons.append('published')
        for active, reference in references:
            if reference.get('run_id') == run_id:
                reasons.append('active' if active else 'reference_held')
                if reference.get('published_at') is not None:
                    reasons.append('published')
            if reference.get('previous_run_id') == run_id:
                reasons.append('rollback')
        run_files = [f for f in files if f['path'].startswith(manifest_prefix + run_id + '.')]
        runs.append({'run_id': run_id, 'status': value.get('status', 'unknown'),
                     'namespace': value.get('namespace'), 'record_count': value.get('record_count'),
                     'xml_hash': value.get('xml_hash'), 'local_bytes': sum(f['local_bytes'] for f in run_files),
                     'shared_snapshot_bytes': 0, 'protected_reasons': sorted(set(reasons)),
                     'selected': run_id in selected, 'cleanup_allowed': False,
                     'provider_usage_scope': 'initial_and_resumed_ingestion',
                     'provider_usage': value.get('usage') if isinstance(value.get('usage'), dict) else None,
                     'usage_may_include_unreported_retries': bool(value.get('usage_may_include_unreported_retries')),
                     'created_at': value.get('created_at') if type(value.get('created_at')) in (int, float) else 0,
                     '_previous_run_id': value.get('previous_run_id')})
    rollback_ids = set()
    for run in runs:
        previous = run.pop('_previous_run_id')
        if isinstance(previous, str) and _RUN_ID.fullmatch(previous):
            rollback_ids.add(previous)
    for run in runs:
        if run['run_id'] in rollback_ids and 'rollback' not in run['protected_reasons']:
            run['protected_reasons'].append('rollback')

    # Repair ledgers are separate from immutable build manifests. Missing or
    # unfinished responses are never presented as zero-cost successful repairs.
    operations = []
    unreadable_repair_usage = False
    for path in sorted((root/'data/health/operations').glob('*.json')):
        if path.is_symlink():
            warnings.append('Skipped repair usage symlink: ' + label(path))
            unreadable_repair_usage = True
            continue
        value = _json(path)
        if value and value.get('operation') == 'repair':
            operations.append(value)
        else:
            warnings.append('A repair usage report could not be read: ' + label(path))
            unreadable_repair_usage = True
    for run in runs:
        repairs = [op for op in operations if op.get('run_id') == run['run_id']]
        tokens = 0
        incomplete = unreadable_repair_usage
        for op in repairs:
            usage = op.get('usage')
            reported = usage.get('embed_total_tokens') if isinstance(usage, dict) else None
            valid = type(reported) in (int, float) and math.isfinite(reported) and reported >= 0
            if valid:
                tokens += reported
            incomplete |= (not valid or op.get('status') != 'completed'
                           or bool(op.get('request_in_progress'))
                           or bool(op.get('usage_may_include_unreported_retries')))
        run['repair_provider_usage_scope'] = 'recorded_repair_operations_only'
        run['repair_provider_usage'] = {'embed_total_tokens': tokens}
        run['repair_operation_count'] = len(repairs)
        run['repair_usage_may_be_incomplete'] = incomplete

    snapshots = []
    corpus_prefix = label(corpora) + '/'
    groups = {}
    for entry in files:
        if entry['path'].startswith(corpus_prefix):
            rest = entry['path'][len(corpus_prefix):]
            if '/' in rest:
                groups.setdefault(rest.split('/')[0], []).append(entry)
    for xml_hash, entries in sorted(groups.items()):
        run_ids = sorted(r['run_id'] for r in runs if r['xml_hash'] == xml_hash)
        size = sum(f['local_bytes'] for f in entries)
        snapshots.append({'xml_hash': xml_hash, 'local_bytes': size, 'run_ids': run_ids,
                          'protected_reasons': ['reference_history_unproven'], 'cleanup_allowed': False})
        for run in runs:
            if run['xml_hash'] == xml_hash:
                run['shared_snapshot_bytes'] = size
    runs.sort(key=lambda r: r['run_id'])
    observed = [r for r in runs if r['provider_usage'] is not None]
    latest = max(observed, key=lambda r: (r['created_at'], r['run_id'])) if observed else None
    usage = ({'run_id': latest['run_id'], 'usage_scope': 'initial_and_resumed_ingestion',
              'usage': latest['provider_usage'],
              'usage_may_include_unreported_retries': latest['usage_may_include_unreported_retries']}
             if latest else None)
    signature = json.dumps({'files': signatures, 'settings': config.settings}, sort_keys=True, default=str)
    # Keep only nonsecret configuration for apply-time revalidation.
    safe_config = AppConfig(copy.deepcopy(config.settings), root)
    return CleanupPlan(selected_run_ids=selected, runs=runs, snapshots=snapshots, files=files,
                       local_bytes=sum(f['local_bytes'] for f in files),
                       fingerprint=hashlib.sha256(signature.encode()).hexdigest(), warnings=warnings,
                       last_provider_usage=usage, _config=safe_config)


def apply_cleanup(plan):
    """Revalidate explicit selection/references and retain all unproven assets.

    No remote request (including a deletion request) is sent. In particular,
    HTTP 202 request acceptance would not establish remote deletion completion.
    """
    if not isinstance(plan, CleanupPlan) or not isinstance(plan._config, AppConfig):
        raise ValueError('A local cleanup preview is required.')
    current = plan_cleanup(plan._config, selected_run_ids=plan.selected_run_ids)
    runs = {r['run_id']: r for r in current.runs}
    retained = []
    for run_id in current.selected_run_ids:
        row = runs.get(run_id)
        retained.append({'run_id': run_id, 'protected_reasons': row['protected_reasons'] if row else
                         ['manifest_unavailable', 'reference_history_unproven']})
    return CleanupReport(selected_run_ids=current.selected_run_ids, deleted_run_ids=[], retained=retained,
                         changed_since_preview=current.fingerprint != plan.fingerprint,
                         warnings=current.warnings)
