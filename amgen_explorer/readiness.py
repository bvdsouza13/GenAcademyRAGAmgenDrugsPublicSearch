"""Explicit readiness checks; last observations never imply continuous health."""
import hashlib
import json
import time


def _fingerprint(config):
    return hashlib.sha256(json.dumps(config.settings, sort_keys=True).encode()).hexdigest()


def latest_readiness(config):
    path = config.root / 'data/health/readiness.json'
    try:
        report = json.loads(path.read_text())
        if not isinstance(report, dict) or report.get('config_fingerprint') != _fingerprint(config):
            return None
        if not isinstance(report.get('checked_at'), (int, float)):
            return None
        return report
    except (OSError, ValueError):
        return None


def check_readiness(service, *, require_generation=False):
    """Called by an explicit Admin action; may consume provider API usage."""
    from .service import atomic_json
    report = {'checked_at': time.time(), 'config_fingerprint': _fingerprint(service.config),
              'source_reading': {'ok': False}, 'semantic_search': {'ok': False, 'state': 'not_checked'},
              'model_access': {'ok': False}, 'generation': {'ok': False, 'state': 'not_checked'},
              'generation_requested': require_generation, 'ok': False,
              'note': 'Last observed state only. Provider availability and credentials can change after this check.'}
    connections = service.connection_status()
    report['model_access'] = {'ok': connections.get('openai', {}).get('ok') is True,
                              'http_status': connections.get('openai', {}).get('http_status')}
    report['index_profile'] = {'ok': connections.get('pinecone', {}).get('ok') is True,
                               'http_status': connections.get('pinecone', {}).get('http_status')}
    try:
        run = service.library_version()
        if run and run.get('full_library'):
            corpus = service.library_corpus(run['run_id'])
            document = next((doc for doc in corpus.documents if doc.product_id == 'product-actimmune'), corpus.documents[0])
            product = next(p for p in corpus.products if p.id == document.product_id)
            report['run_id'] = run['run_id']
            report['source_reading'] = {'ok': True}
            results = service.search_library(product.name, run_id=run['run_id'],
                                             document_ids=[document.id])
            semantic_ok = bool(results.hits) and not results.degraded
            report['semantic_search'] = {'ok': semantic_ok, 'state': 'available' if semantic_ok else 'degraded'}
            if require_generation:
                response = service.answer('What mechanism of action does the source describe?', product.id,
                                          document_id=document.id, run_id=run['run_id'])
                verified = (not response.abstained and bool(response.citations)
                            and not response.usage.get('source_fallback')
                            and not response.usage.get('provider_problem')
                            and response.usage.get('explanation_verified') is True)
                state = 'verified' if verified else ('provider_unavailable' if response.usage.get('provider_problem') else 'source_fallback')
                report['generation'] = {'ok': verified, 'state': state,
                                        'citation_count': len(response.citations)}
    except Exception:
        # Never retain arbitrary exception text, which could contain provider data.
        report['diagnostic'] = 'The library or a provider check could not complete. Inspect source integrity and connection settings.'
    report['ok'] = all(report[key]['ok'] for key in ('source_reading', 'semantic_search', 'model_access', 'index_profile'))
    if require_generation:
        report['ok'] = report['ok'] and report['generation']['ok']
    atomic_json(service.config.root / 'data/health/readiness.json', report)
    return report
