#!/usr/bin/env python3
"""Check frozen condition-to-treatment cases; local by default, explicit --live reads only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amgen_explorer.config import load_config
from amgen_explorer.indexing import read_json
from amgen_explorer.search import search_local
from amgen_explorer.service import ExplorerService

LIMITATIONS = [
    'Measures exact product sets and first evidence per product, including explicitly audited contiguous source pairs; not clinical precision of every passage.',
    'No generated answers or clinical recommendations are evaluated; source labels may not be current.',
    'Expected products and evidence never become search filters. Local mode makes no provider calls.',
]


def validate_fixture(fixture, corpus):
    """Reject stale expectations; never rebind quotes to make a case pass."""
    if fixture.get('schema_version') != 1 or fixture['corpus']['xml_sha256'] != corpus.xml_hash:
        raise ValueError('Fixture XML identity does not match the pinned corpus.')
    documents = {d.id: d for d in corpus.documents}
    rows = fixture['source_documents']
    if len(rows) != len(documents) or {r['document_id'] for r in rows} != set(documents):
        raise ValueError('Fixture PDF inventory does not match the pinned corpus.')
    for row in rows:
        doc = documents[row['document_id']]
        if (row['sha256'], row['product_id'], row['filename'], row['page_count']) != (
                doc.sha256, doc.product_id, doc.filename, doc.page_count):
            raise ValueError('Fixture PDF identity does not match the pinned corpus.')
    blocks = {b.id: b for b in corpus.blocks}
    for evidence in fixture['evidence'].values():
        block = blocks.get(evidence['block_id'])
        if block is None:
            raise ValueError('Fixture source block is absent from the pinned corpus.')
        if evidence['quote_exact'] != block.text:
            raise ValueError('Fixture quote does not match its exact pinned source block.')
        if evidence['block_sha256'] != block.content_hash or hashlib.sha256(block.text.encode()).hexdigest() != block.content_hash:
            raise ValueError('Fixture block hash does not match the pinned source.')
        if evidence['source_spans'] != block.spans:
            raise ValueError('Fixture source span does not match the pinned block.')
        if (evidence['product_id'], evidence['document_id'], evidence['pdf_sha256'], evidence['pdf_filename']) != (
                block.product_id, block.document_id, block.document_sha256, documents[block.document_id].filename):
            raise ValueError('Fixture evidence PDF identity does not match the pinned block.')
        if (evidence['physical_pdf_page'], evidence['section_id'], evidence['section_title'], evidence['section_kind']) != (
                block.page_start, block.section_id, block.section_title, block.section_kind):
            raise ValueError('Fixture section identity does not match the pinned block.')
        for span in block.spans:
            archive = blocks.get(span['block_id'])
            if archive is None or archive.text[span['start']:span['end']] != block.text:
                raise ValueError('Fixture quote does not resolve to its pinned archive span.')
    cases = fixture['acceptance_cases']
    if not 1 <= len(cases) <= 100 or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Fixture requires one to 100 uniquely identified cases.')
    products = {p.id for p in corpus.products}
    for case in cases:
        expected = case['expected_treatment_product_ids']
        if len(set(expected)) != len(expected) or not set(expected) <= products:
            raise ValueError('Fixture expected product identity is invalid.')
        refs = case['supporting_evidence_refs'] + case['negative_or_qualifying_evidence_refs']
        if not all(ref in fixture['evidence'] for ref in refs):
            raise ValueError('Fixture evidence reference is missing.')
        leading = case['expected_leading_evidence']
        if set(leading) != set(expected):
            raise ValueError('Each expected product requires independent leading evidence.')
        for product, refs in leading.items():
            if not refs or not all(ref in case['supporting_evidence_refs'] and
                    fixture['evidence'][ref]['product_id'] == product for ref in refs):
                raise ValueError('Fixture leading evidence does not support its expected product.')
        for product, pair in case.get('required_leading_evidence_pairs', {}).items():
            refs = pair['evidence_refs']
            if (pair['xml_sha256'] != corpus.xml_hash or product not in leading
                    or len(refs) != 2 or len(set(refs)) != 2
                    or not all(ref in case['supporting_evidence_refs'] and
                               fixture['evidence'][ref]['product_id'] == product for ref in refs)
                    or refs[-1] not in leading[product]
                    or len({fixture['evidence'][ref]['document_id'] for ref in refs}) != 1):
                raise ValueError('Fixture paired evidence has inconsistent source identity.')
        queries = [case['query'], *case.get('query_variants', [])]
        if not all(isinstance(q, str) and q.strip() for q in queries):
            raise ValueError('Fixture queries must be nonempty text.')


def _block_ids(hit):
    meta = hit.get('metadata', {})
    ids = meta.get('block_ids', [])
    spans = meta.get('source_spans', [])
    if isinstance(ids, str):
        ids = json.loads(ids)
    if isinstance(spans, str):
        spans = json.loads(spans)
    return set(ids) | {s['source_block_id'] for s in spans if s.get('source_block_id')}


def _exact_pair_member(hit, evidence, xml_hash):
    """Match the whole audited fragment, without consulting matcher assertions."""
    meta = hit.get('metadata', {})
    if (hit.get('text') != evidence['quote_exact'] or hit.get('xml_hash') != xml_hash
            or meta.get('xml_hash') != xml_hash
            or hit.get('product_id') != evidence['product_id']
            or meta.get('product_id') != evidence['product_id']
            or hit.get('document_id') != evidence['document_id']
            or meta.get('document_id') != evidence['document_id']
            or meta.get('document_sha256') != evidence['pdf_sha256']
            or _block_ids(hit) != {evidence['block_id']}):
        return False
    spans = meta.get('source_spans', [])
    if isinstance(spans, str):
        spans = json.loads(spans)
    expected = [{'source_block_id': evidence['block_id'], 'archive_block_id': s['block_id'],
                 'page': s['page'], 'start': s['start'], 'end': s['end'],
                 'block_start': 0, 'block_end': len(evidence['quote_exact'])}
                for s in evidence['source_spans']]
    return spans == expected


def score_case(case, hits, evidence, *, live=False, degraded=False):
    """Judge literal audited provenance, independently of runtime condition matching."""
    first = {}
    positions = {}
    for index, hit in enumerate(hits):
        product = hit.get('metadata', {}).get('product_id') or hit.get('product_id') or '<missing-product>'
        first.setdefault(product, hit)
        positions.setdefault(product, index)
    expected = set(case['expected_treatment_product_ids'])
    actual = set(first)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    leading_failures = []
    leading_blocks = {}
    for product in sorted(expected & actual):
        leading_blocks[product] = sorted(_block_ids(first[product]))
        allowed = {evidence[ref]['block_id'] for ref in case['expected_leading_evidence'][product]}
        pair = case.get('required_leading_evidence_pairs', {}).get(product)
        if pair:
            adjacent = hits[positions[product]:positions[product]+2]
            valid = len(adjacent) == 2 and all(
                _exact_pair_member(hit, evidence[ref], pair['xml_sha256'])
                for hit, ref in zip(adjacent, pair['evidence_refs']))
            if valid:
                leading_blocks[product] = [evidence[ref]['block_id'] for ref in pair['evidence_refs']]
        else:
            valid = bool(allowed.intersection(leading_blocks[product]))
        if not valid:
            leading_failures.append(product)
    failures = []
    if missing: failures.append('missing_expected_products')
    if unexpected: failures.append('unexpected_products')
    if leading_failures: failures.append('leading_evidence_not_audited_indication')
    if live and degraded: failures.append('degraded_live_search')
    return {'passed': not failures, 'failures': failures,
            'expected_product_ids': sorted(expected), 'actual_product_ids': sorted(actual),
            'missing_product_ids': missing, 'unexpected_product_ids': unexpected,
            'leading_evidence_failures': leading_failures, 'leading_source_block_ids': leading_blocks,
            'hit_count': len(hits), 'degraded': degraded}


def _citation_valid(hit, corpus, service, resolved):
    meta = hit.get('metadata', {})
    did = meta.get('document_id')
    # Even an invalid citation must not avoid the source resolver check.
    if did not in resolved:
        try:
            resolved[did] = bool(service.source_pdf(did, corpus.xml_hash))
        except Exception:
            resolved[did] = False
    doc = next((d for d in corpus.documents if d.id == did), None)
    return bool(resolved[did] and doc and hit.get('xml_hash') == corpus.xml_hash
                and meta.get('document_sha256') == doc.sha256
                and meta.get('product_id') == doc.product_id
                and hit.get('document_id', did) == did
                and hit.get('product_id', doc.product_id) == doc.product_id
                and type(meta.get('page_start')) is int and type(meta.get('page_end')) is int
                and 1 <= meta['page_start'] <= meta['page_end'] <= doc.page_count)


def evaluate_fixture(service, run, fixture, *, live=False):
    """Read the pinned active run; never build artifacts, upsert, or change scope."""
    if not run or run.get('status') != 'verified':
        raise ValueError('A verified active local library is required.')
    corpus = service._pinned_corpus(run.get('xml_hash'))
    validate_fixture(fixture, corpus)
    limit = service.config.settings.get('search', {}).get('result_limit', 20)
    resolved = {}
    results = []
    for case in fixture['acceptance_cases']:
        queries = list(dict.fromkeys([case['query'], *case.get('query_variants', [])]))
        for number, query in enumerate(queries):
            started = time.perf_counter()
            row = {'case_id': case['id'], 'query_index': number, 'query': query}
            try:
                if live:
                    result = service.search_library(query, run_id=run['run_id'], limit=limit)
                else:
                    result = search_local(query, run, service.config, corpus, limit=limit)
                row.update(score_case(case, result.hits, fixture['evidence'], live=live, degraded=result.degraded))
                row['citation_failure_count'] = sum(not _citation_valid(hit, corpus, service, resolved)
                                                    for hit in result.hits)
                if row['citation_failure_count']:
                    row['failures'].append('citation_resolution_failed')
                if result.xml_hash != run['xml_hash'] or result.run_id != run['run_id']:
                    row['failures'].append('result_run_identity_mismatch')
                row['outcome'] = result.outcome
                row['ranking_version'] = result.ranking_version
                row['usage'] = result.usage
                row['passed'] = not row['failures']
            except Exception:
                # Provider and file exceptions may contain paths or credentials.
                row.update(passed=False, failures=['search_or_citation_check_failed'], citation_failure_count=0)
            row['latency_ms'] = round((time.perf_counter() - started) * 1000, 3)
            results.append(row)
    failed_cases = sorted({r['case_id'] for r in results if not r['passed']})
    return {'schema_version': 1, 'measured_at': datetime.now(timezone.utc).isoformat(),
            'mode': 'live_read_only' if live else 'local_read_only',
            'run_id': run['run_id'], 'xml_hash': run['xml_hash'], 'result_limit': limit,
            'provider_calls_requested': len(results) if live else 0,
            'case_count': len(fixture['acceptance_cases']), 'failed_case_count': len(failed_cases),
            'failed_case_ids': failed_cases, 'query_count': len(results),
            'passed_query_count': sum(r['passed'] for r in results),
            'failed_query_count': sum(not r['passed'] for r in results),
            'resolved_citation_document_count': sum(resolved.values()),
            'failed_citation_document_count': sum(not v for v in resolved.values()),
            'limitations': LIMITATIONS, 'results': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--fixture', type=Path, default=Path(__file__).resolve().parents[1]/'evals/condition-search.json')
    parser.add_argument('--live', action='store_true', help='Explicit read-only provider search; never builds or upserts.')
    parser.add_argument('--output', type=Path, help='Optional JSON report inside ignored output/condition-search/.')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        destination = args.output.resolve() if args.output else None
        allowed = (config.root/'output/condition-search').resolve()
        if destination and (destination == allowed or not destination.is_relative_to(allowed)):
            raise ValueError('Output must be inside ignored output/condition-search/.')
        payload = args.fixture.read_bytes()
        fixture = json.loads(payload)
        service = ExplorerService(config)
        run = read_json(config.path('active_corpus_manifest'))
        report = evaluate_fixture(service, run, fixture, live=args.live)
        report['fixture_sha256'] = hashlib.sha256(payload).hexdigest()
        output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(output+'\n')
        print(output)
        return int(report['failed_query_count'] > 0)
    except (ValueError, OSError, TypeError, KeyError):
        print('Condition evaluation failed before grading: check fixture and pinned library integrity.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
