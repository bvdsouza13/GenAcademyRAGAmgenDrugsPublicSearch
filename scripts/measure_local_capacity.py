#!/usr/bin/env python3
"""Measure pinned local search/page rendering, with no provider or state writes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import resource
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amgen_explorer.config import load_config
from amgen_explorer.indexing import read_json
from amgen_explorer.search import search_local
from amgen_explorer.service import ExplorerService, _read_corpus


def _rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def _summary(values):
    ordered = sorted(values)
    return {'samples': len(values), 'median_ms': round(statistics.median(values), 3),
            'p95_ms': round(ordered[max(0, math.ceil(.95 * len(ordered)) - 1)], 3),
            'max_ms': round(max(values), 3)}


def measure_capacity(config, *, concurrency=(1, 5), iterations=3,
                     queries=('What are the warnings?', 'How should medicines be stored?', 'What is the dosage?')):
    """Use threads as concurrent read sessions in one local application process.

    Cold means the application's XML parser cache was cleared immediately
    before the batch. OS filesystem caches are neither flushed nor controlled.
    Search repeats all existing pinned-record/artifact/source validation.
    Page rendering verifies pinned XML/PDF bytes on every request.
    """
    if not concurrency or any(type(n) is not int or not 1 <= n <= 5 for n in concurrency):
        raise ValueError('Concurrency must contain integers between one and five.')
    if type(iterations) is not int or not 1 <= iterations <= 20 or not queries:
        raise ValueError('Choose one to twenty iterations and at least one query.')
    service = ExplorerService(config)
    run = read_json(config.path('active_corpus_manifest'))
    if not isinstance(run, dict) or run.get('status') != 'verified':
        raise ValueError('A verified active local library is required.')
    corpus = service._pinned_corpus(run.get('xml_hash'))
    document = next((d for d in corpus.documents if d.id in run.get('document_ids', [])), None)
    if document is None:
        raise ValueError('No pinned source is available for page rendering.')
    memory_before = _rss()
    scenarios = []

    def session(number):
        search_times = []
        page_times = []
        rendered = 0
        hit_count = 0
        for iteration in range(iterations):
            query = queries[(number + iteration) % len(queries)]
            started = time.perf_counter()
            pinned = service._pinned_corpus(run['xml_hash'])
            result = search_local(query, run, config, pinned)
            search_times.append((time.perf_counter() - started) * 1000)
            hit_count += len(result.hits)
            started = time.perf_counter()
            payload = service.source_page(document.id, 1, run['xml_hash'])
            page_times.append((time.perf_counter() - started) * 1000)
            rendered += len(payload)
        return search_times, page_times, rendered, hit_count

    for count in concurrency:
        scenario = {'concurrency': count, 'iterations_per_session': iterations}
        for phase in ('cold', 'warm'):
            if phase == 'cold':
                _read_corpus.cache_clear()
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=count) as pool:
                samples = list(pool.map(session, range(count)))
            scenario[phase] = {
                'wall_ms': round((time.perf_counter() - started) * 1000, 3),
                'search': {**_summary([v for row in samples for v in row[0]]),
                           'returned_hits': sum(row[3] for row in samples)},
                'page_render': {**_summary([v for row in samples for v in row[1]]),
                                'rendered_bytes': sum(row[2] for row in samples)},
                'peak_process_rss_bytes': _rss()}
        scenarios.append(scenario)
    return {'measured_at': datetime.now(timezone.utc).isoformat(), 'run_id': run['run_id'],
            'xml_hash': run['xml_hash'], 'record_count': run.get('record_count'),
            'document_count': len(corpus.documents), 'page_count': sum(d.page_count for d in corpus.documents),
            'queries': list(queries), 'page_render_document_id': document.id, 'page_render_page': 1,
            'provider_calls': 0, 'scenarios': scenarios,
            'memory': {'before_peak_process_rss_bytes': memory_before, 'peak_process_rss_bytes': _rss(),
                       'scope': 'whole process high-water RSS; shared across threads, includes imports and caches'},
            'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                            'logical_cpu_count': __import__('os').cpu_count()},
            'limitations': ['Cold is application XML-cache cold; OS filesystem cache is uncontrolled.',
                            'Five concurrent threads share one process; this does not measure public hosting.',
                            'Page rendering measures one pinned PDF page, not a browser or Streamlit UI render.',
                            'Concurrent workload latency includes integrity validation; no validation cache was added.',
                            'RSS is a process high-water mark, not isolated per-request allocation.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        destination = None
        if args.output:
            destination = args.output.resolve()
            allowed = (config.root / 'output/remediation').resolve()
            if not destination.is_relative_to(allowed) or destination == allowed:
                raise ValueError('Capacity output must be inside output/remediation.')
        report = measure_capacity(config, iterations=args.iterations)
        payload = json.dumps(report, indent=2, allow_nan=False)
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(payload + '\n')
        print(payload)
        return 0
    except (ValueError, OSError, TypeError, KeyError):
        print('Capacity measurement failed: check configuration and pinned local library integrity.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
