#!/usr/bin/env python3
"""Inspect the active library; cloud checks are explicit and read-only.

Writes only the requested report. Never imports, builds, uploads, activates, or
repairs a library. --live and --verify-remote consume Pinecone API usage.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amgen_explorer.connectivity import ProviderError
from amgen_explorer.indexing import manifest_records
from amgen_explorer.service import ExplorerService
from amgen_explorer.teaching import _incomplete_continuations, _sources
from scripts.setup_pinecone import SetupError


def assess(service, *, live=False, verify_remote=False):
    active_path = service.config.path('active_corpus_manifest')
    before = hashlib.sha256(active_path.read_bytes()).hexdigest()
    run = service.library_version()
    corpus = service.library_corpus(run['run_id'])
    records = manifest_records(run, service.config)
    suite = [json.loads(line) for line in (service.config.root / 'evals/global-search.jsonl').read_text().splitlines() if line.strip()]
    measured = [row for row in suite if row.get('expected_document_ids')]
    report = {
        'run_id': run['run_id'], 'xml_hash': run['xml_hash'],
        'documents': len(corpus.documents), 'products': len(corpus.products),
        'records': len(records), 'settings': {
            'chunking': run.get('chunk_settings'),
            'retrieval': service.config.settings['retrieval'],
        },
        'layout_limited_records': sum(bool(r.get('extraction_limitations')) for r in records),
        'documents_with_layout_limited_records': len({r['document_id'] for r in records if r.get('extraction_limitations')}),
        'continuation_records': sum(bool(r.get('continuation_parent_ids')) for r in records),
        'evaluation_scope': {
            'retrieval_cases': len(measured),
            'prefiltered_cases': sum(bool(row.get('product_id') or row.get('document_id')) for row in measured),
            'unfiltered_cases': sum(not (row.get('product_id') or row.get('document_id')) for row in measured),
            'behavioral_cases_not_scored_by_chunk_comparison': len(suite) - len(measured),
        },
        'live': live, 'evidence_probes': [],
        'interpretation': 'Readiness gates and retrieval observations, not clinical correctness or successful OpenAI generation.',
    }
    if verify_remote:
        start = time.monotonic()
        index = service.index
        index.verification_attempts = 1
        try:
            index.client.check()
            index._verify(run, records)
            report['remote_verification'] = {'ok': True, 'expected_records_matched': len(records),
                                             'document_scopes_searchable': len(run['document_ids'])}
        except (ProviderError, SetupError, ValueError, OSError):
            report['remote_verification'] = {'ok': False, 'message': 'Remote verification failed; no repairs or writes were attempted.'}
        report['remote_verification']['seconds'] = round(time.monotonic() - start, 3)
    if live:
        question = 'How does this medicine work? Explain its mechanism of action.'
        for document in corpus.documents:
            start = time.monotonic()
            row = {'document_id': document.id, 'product_id': document.product_id, 'question': question}
            try:
                evidence = service._evidence(question, document.product_id, document.id, run_id=run['run_id'])
                sources = _sources(evidence)
                state = 'eligible_for_generation'
                if not sources:
                    state = 'no_verified_evidence'
                elif any(p['metadata'].get('extraction_limitations') for p in sources.values()):
                    state = 'layout_source_fallback'
                elif _incomplete_continuations(sources) or any('continuation context' in w.lower() for w in evidence.warnings):
                    state = 'incomplete_context_source_fallback'
                row.update(state=state, passages=len(sources), warnings=list(dict.fromkeys(evidence.warnings)),
                           sections=sorted({p['metadata']['section_title'] for p in sources.values()}))
            except ProviderError as exc:
                row.update(state='provider_error', http_status=exc.status)
            except (ValueError, OSError):
                row.update(state='local_validation_error')
            row['seconds'] = round(time.monotonic() - start, 3)
            report['evidence_probes'].append(row)
        report['probe_summary'] = dict(Counter(row['state'] for row in report['evidence_probes']))
        report['probe_mean_seconds'] = round(statistics.mean(row['seconds'] for row in report['evidence_probes']), 3)
    report['active_pointer_unchanged'] = before == hashlib.sha256(active_path.read_bytes()).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicit read-only Pinecone retrieval for each document; no OpenAI generation.')
    parser.add_argument('--verify-remote', action='store_true', help='Fetch and compare every expected remote record and search every document scope; no writes.')
    parser.add_argument('--output', type=Path, default=Path('output/failure-assessment/library-audit.json'))
    args = parser.parse_args()
    report = assess(ExplorerService(), live=args.live, verify_remote=args.verify_remote)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('documents', 'records', 'layout_limited_records', 'evaluation_scope', 'active_pointer_unchanged')}))
    if args.live:
        print(json.dumps(report['probe_summary']))
    if args.verify_remote:
        print(json.dumps(report['remote_verification']))
    return 0 if report['active_pointer_unchanged'] and report.get('remote_verification', {}).get('ok', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
