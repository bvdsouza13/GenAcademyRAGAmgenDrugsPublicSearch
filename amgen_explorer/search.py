"""Run-pinned global discovery, separate from source-scoped teaching evidence.

The local SQLite artifact is created only by an explicit build. Search validates
its content against immutable run records before querying either search engine.
No provider, filesystem mutation or background search occurs on module import.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from .connectivity import DocumentsClient, ProviderError
from .indexing import digest, guard_text, manifest_records, validate_manifest_records
from scripts.setup_pinecone import SetupError

RANKING_VERSION = 'global-rrf-v1'


@dataclass(frozen=True)
class SearchArtifact:
    path: str
    sha256: str
    run_id: str
    xml_hash: str
    records_digest: str
    catalog_digest: str
    ranking_version: str
    engine: str
    policy_fingerprint: str


@dataclass
class SearchResults:
    query: str
    run_id: str
    namespace: str
    xml_hash: str
    hits: list[dict] = field(default_factory=list)
    groups: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    ranking_version: str = RANKING_VERSION
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _policy_fingerprint(run):
    # Include the complete policy pin even for legacy manifests without a marker.
    return digest({k: v for k, v in run.items() if 'policy' in k or k == 'schema_version'})


def _artifact_path(run, config):
    return config.path('manifest_dir') / (run['run_id'] + '.' + RANKING_VERSION + '.sqlite')


def _catalog(run, records, corpus):
    if corpus is None or corpus.xml_hash != run.get('xml_hash'):
        raise ValueError('Search artifact requires the pinned XML corpus.')
    products = {p.id: p for p in corpus.products}
    documents = {d.id: d for d in corpus.documents}
    rows = []
    for record in sorted(records, key=lambda r: r['_id']):
        doc = documents.get(record['document_id'])
        product = products.get(record['product_id'])
        if (doc is None or product is None or doc.product_id != product.id
                or doc.sha256 != record.get('document_sha256')
                or not 1 <= record.get('page_start', 0) <= record.get('page_end', 0) <= doc.page_count):
            raise ValueError('Search artifact source identity does not match the pinned corpus.')
        rows.append({'id':record['_id'], 'product_id':product.id, 'document_id':doc.id,
                     'product_name':product.name, 'generic_name':product.generic_name,
                     'filename':doc.filename, 'variant_hint':doc.variant_hint, 'revision':doc.revision})
    return rows


def _pin(run, records, catalog):
    return {'run_id':run['run_id'], 'xml_hash':run['xml_hash'], 'records_digest':digest(records),
            'catalog_digest':digest(catalog), 'ranking_version':RANKING_VERSION,
            'policy_fingerprint':_policy_fingerprint(run)}


def _record_rows(records, catalog, text_field):
    names = {r['id']:r for r in catalog}
    return [(r['_id'], r.get('source_text', r[text_field]), str(r.get('section_title', '')),
             names[r['_id']]['product_name'], names[r['_id']]['generic_name'], _json(r))
            for r in sorted(records, key=lambda r: r['_id'])]


@contextmanager
def _open_payload(payload):
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(payload)
        db.execute('PRAGMA query_only=ON')
        yield db
    finally:
        db.close()


def build_search_artifact(run, records, corpus, config, *, use_fts5=True):
    """Build the immutable lexical half of one run; never contacts a provider.

    Persist ``asdict(result)`` as ``run['search_artifact']`` before activation.
    FTS5 availability is checked by actually creating its virtual table. Systems
    without it retain the same authoritative rows and use deterministic tokens.
    """
    validate_manifest_records(run, records, config)
    catalog = _catalog(run, records, corpus)
    pin = _pin(run, records, catalog)
    path = _artifact_path(run, config)
    if run.get('search_artifact') is not None:
        # An already-published checksum is authoritative. A retry must never
        # refresh that checksum to bless changed bytes, even if display rows
        # happen to remain unchanged.
        return validate_search_artifact(run, records, config, corpus)
    if path.exists():
        # Reuse is content checked, including when resuming a build interrupted
        # before its artifact descriptor was saved to the manifest.
        try:
            payload = path.read_bytes()
            with _open_payload(payload) as db:
                engine = json.loads(db.execute('SELECT value FROM metadata WHERE key=?', ('engine',)).fetchone()[0])
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise ValueError('Existing search artifact is unavailable or changed.') from None
        candidate = SearchArtifact(str(path.relative_to(config.root)), hashlib.sha256(payload).hexdigest(), **pin, engine=engine)
        validate_search_artifact({**run, 'search_artifact':asdict(candidate)}, records, config, corpus)
        return candidate
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.search-', suffix='.sqlite', dir=path.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE catalog (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE records (id TEXT PRIMARY KEY, source_text TEXT NOT NULL, heading TEXT NOT NULL, brand TEXT NOT NULL, generic TEXT NOT NULL, payload TEXT NOT NULL)')
            rows = _record_rows(records, catalog, config.settings['pinecone']['text_field'])
            db.executemany('INSERT INTO records VALUES (?,?,?,?,?,?)', rows)
            db.executemany('INSERT INTO catalog VALUES (?,?)', [(r['id'],_json(r)) for r in catalog])
            engine = 'fallback'
            if use_fts5:
                try:
                    db.execute('CREATE VIRTUAL TABLE records_fts USING fts5(id UNINDEXED, source_text, heading, brand, generic, tokenize="unicode61 remove_diacritics 2")')
                except sqlite3.OperationalError as exc:
                    if 'no such module' not in str(exc).lower():
                        raise
                else:
                    db.executemany('INSERT INTO records_fts VALUES (?,?,?,?,?)', [row[:5] for row in rows])
                    engine = 'fts5'
            db.executemany('INSERT INTO metadata VALUES (?,?)', [(key,_json(value)) for key,value in {**pin,'engine':engine}.items()])
        payload = Path(temporary).read_bytes()
        # Link creates the final identity atomically without overwriting another
        # builder's file or a previously retained version.
        try:
            os.link(temporary, path)
        except FileExistsError:
            return build_search_artifact(run, records, corpus, config, use_fts5=use_fts5)
        artifact = SearchArtifact(str(path.relative_to(config.root)), hashlib.sha256(payload).hexdigest(), **pin, engine=engine)
        validate_search_artifact({**run,'search_artifact':asdict(artifact)}, records, config, corpus)
        return artifact
    except sqlite3.Error:
        raise ValueError('Unable to construct the local search artifact.') from None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validated_payload(run, records, config, corpus=None):
    validate_manifest_records(run, records, config)
    try:
        artifact = SearchArtifact(**run['search_artifact'])
        path = (config.root / artifact.path).resolve()
        if path != _artifact_path(run, config).resolve() or not path.is_relative_to(config.root):
            raise ValueError()
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != artifact.sha256:
            raise ValueError()
        with _open_payload(payload) as db:
            catalog = [json.loads(row[0]) for row in db.execute('SELECT payload FROM catalog ORDER BY id')]
            expected_catalog = _catalog(run, records, corpus) if corpus is not None else catalog
            pin = _pin(run, records, expected_catalog)
            expected = {**pin, 'engine':artifact.engine}
            if artifact.engine not in {'fts5','fallback'}:
                raise ValueError()
            if any(getattr(artifact, key) != value for key,value in pin.items()):
                raise ValueError()
            meta = {key:json.loads(value) for key,value in db.execute('SELECT key,value FROM metadata')}
            if meta != expected or catalog != expected_catalog:
                raise ValueError()
            rows = db.execute('SELECT id,source_text,heading,brand,generic,payload FROM records ORDER BY id').fetchall()
            expected_rows = _record_rows(records, expected_catalog, config.settings['pinecone']['text_field'])
            if rows != expected_rows:
                raise ValueError()
            if artifact.engine == 'fts5':
                fts_rows = db.execute('SELECT id,source_text,heading,brand,generic FROM records_fts ORDER BY id').fetchall()
                if fts_rows != [row[:5] for row in expected_rows]:
                    raise ValueError()
        return artifact, payload
    except (KeyError, TypeError, OSError, sqlite3.Error, ValueError):
        raise ValueError('The pinned search artifact is missing, incompatible or failed integrity validation. Build and verify the library again.') from None


def validate_search_artifact(run, records, config, corpus=None):
    """Fail closed on stale content, path substitution or changed policy/ranking."""
    return _validated_payload(run, records, config, corpus)[0]


def build_lexical_artifact(run, records, corpus, config):
    """Dictionary adapter for manifest orchestration."""
    return asdict(build_search_artifact(run, records, corpus, config))


validate_lexical_artifact = validate_search_artifact


def _tokens(text):
    return re.findall(r'[^\W_]+', text.casefold(), flags=re.UNICODE)


def _lexical_ids(payload, engine, query):
    tokens = list(dict.fromkeys(_tokens(query)))
    if not tokens:
        return []
    with _open_payload(payload) as db:
        if engine == 'fts5':
            expression = ' OR '.join('"'+token+'"' for token in tokens)
            return [r[0] for r in db.execute('SELECT id FROM records_fts WHERE records_fts MATCH ? ORDER BY bm25(records_fts,0,1,1.5,2,2), id', (expression,))]
        ranked = []
        for rid, text, heading, brand, generic in db.execute('SELECT id,source_text,heading,brand,generic FROM records'):
            words = set(_tokens(' '.join((text, heading, brand, generic))))
            matched = sum(token in words for token in tokens)
            if matched:
                ranked.append((-matched, rid))
        return [rid for _,rid in sorted(ranked)]


def _spans(record):
    spans = record.get('source_spans', [])
    if isinstance(spans, str):
        try:
            spans = json.loads(spans)
        except ValueError:
            return []
    return spans if isinstance(spans, list) else []


def _overlaps(left, right, text_field):
    if left['document_id'] != right['document_id']:
        return False
    spans_a, spans_b = _spans(left), _spans(right)
    if not spans_a or not spans_b:
        # Legacy records may have no exact offsets. Equal strings alone cannot
        # collapse distinct cited occurrences when coordinates are available.
        a = left.get('source_text', left[text_field])
        b = right.get('source_text', right[text_field])
        return a == b or bool(min(len(a),len(b)) and (a in b or b in a))
    shared = 0
    for x in spans_a:
        for y in spans_b:
            if (x.get('page'),x.get('archive_block_id')) == (y.get('page'),y.get('archive_block_id')):
                shared += max(0, min(x.get('end',0),y.get('end',0))-max(x.get('start',0),y.get('start',0)))
    shortest = min(sum(max(0,s.get('end',0)-s.get('start',0)) for s in spans_a),
                   sum(max(0,s.get('end',0)-s.get('start',0)) for s in spans_b))
    return bool(shortest and shared / shortest >= .5)


def search_library(query, run, config, corpus, *, client=None, product_ids=None, document_ids=None, limit=20):
    """Explicit global discovery call. Teaching must select one returned scope.

    Returned dictionaries preserve original source spans and record metadata;
    rank-fusion scores are retrieval scores, never clinical confidence values.
    Semantic-provider failure preserves verified local text matches and labels
    the response degraded. Invalid local artifacts never fall through to cloud.
    """
    started = time.perf_counter()
    guard_text(query)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Search limit must be between 1 and 100.')
    if not run or run.get('status') != 'verified':
        raise ValueError('Choose a verified library version before searching.')
    for scope in (product_ids, document_ids):
        if scope is not None and (not isinstance(scope, list) or not all(isinstance(v,str) and v for v in scope)):
            raise ValueError('Search filters must be lists of source identities.')
    records = manifest_records(run, config)
    artifact, payload = _validated_payload(run, records, config, corpus)
    result = SearchResults(query, run['run_id'], run['namespace'], run['xml_hash'])
    scoped = {r['_id']:r for r in records if (product_ids is None or r['product_id'] in product_ids)
              and (document_ids is None or r['document_id'] in document_ids)}
    if not scoped:
        result.latency_ms = (time.perf_counter()-started)*1000
        return result
    lexical = [rid for rid in _lexical_ids(payload, artifact.engine, query) if rid in scoped]
    filters = [{ 'xml_hash':{'$eq':run['xml_hash']}}]
    if product_ids is not None:
        filters.append({'product_id':{'$in':sorted(set(product_ids))}})
    if document_ids is not None:
        filters.append({'document_id':{'$in':sorted(set(document_ids))}})
    semantic = []
    client = client or DocumentsClient(config)
    try:
        if not getattr(client, 'host', True):
            client.check()
        hits = client.search(run['namespace'], query, {'$and':filters}, min(100,max(20,limit*3)))
        if not isinstance(hits, list):
            raise ValueError('Invalid semantic result shape.')
        for hit in hits:
            expected = scoped.get(hit.get('_id')) if isinstance(hit,dict) else None
            if expected is None or any(hit.get(k) != v for k,v in expected.items()):
                result.warnings.append('A semantic hit failed pinned source/scope verification and was excluded.')
                continue
            if expected['_id'] not in semantic:
                semantic.append(expected['_id'])
        reported = getattr(client, 'last_usage', None)
        if isinstance(reported,dict):
            result.usage = dict(reported)
    except (ProviderError, SetupError, ValueError, OSError):
        result.degraded = True
        result.warnings.append('Semantic search is unavailable. Showing verified local text search matches only (degraded mode).')
    ranks = {}
    for channel in (lexical, semantic):
        for rank, rid in enumerate(channel, 1):
            ranks[rid] = ranks.get(rid,0) + 1/(60+rank)
    names = {p.id:p for p in corpus.products}
    normalized = ' '.join(_tokens(query))
    for rid in ranks:
        product = names[scoped[rid]['product_id']]
        # At most one quarter of a first-rank RRF contribution. Exact aliases
        # help discovery without overriding relevance across both engines.
        if normalized and normalized in {' '.join(_tokens(product.name)), ' '.join(_tokens(product.generic_name))}:
            ranks[rid] += .004
    ranked = sorted(ranks, key=lambda rid:(-ranks[rid], rid))
    by_document = {}
    field_name = config.settings['pinecone']['text_field']
    for rid in ranked:
        record = scoped[rid]
        key = (record['product_id'], record['document_id'])
        group = by_document.setdefault(key, [])
        if not any(_overlaps(record, scoped[prior], field_name) for prior in group):
            group.append(rid)
    # Round robin prevents a long document's overlapping name hits from hiding
    # other medicines or device variants at the global discovery limit.
    chosen = []
    depth = 0
    while len(chosen) < limit:
        current = [ids[depth] for ids in by_document.values() if len(ids) > depth]
        if not current:
            break
        chosen.extend(current[:limit-len(chosen)])
        depth += 1
    catalog = {r['id']:r for r in _catalog(run, records, corpus)}
    groups = {}
    for rid in chosen:
        record = scoped[rid]
        metadata = {k:v for k,v in record.items() if k not in {'_id',field_name}}
        metadata['source_spans'] = _spans(record)
        hit = {'id':rid, 'text':record.get('source_text',record[field_name]), 'metadata':metadata,
               'run_id':run['run_id'], 'namespace':run['namespace'], 'xml_hash':run['xml_hash'],
               'score':ranks[rid], **{k:v for k,v in catalog[rid].items() if k != 'id'}}
        result.hits.append(hit)
        key = (record['product_id'],record['document_id'])
        groups.setdefault(key, {'product_id':key[0], 'document_id':key[1], 'hits':[]})['hits'].append(hit)
        if record.get('extraction_limitations') or record.get('layout_limitations'):
            result.warnings.append('A source has extraction/layout limitations. View its PDF page before interpreting table or figure relationships.')
    result.groups = list(groups.values())
    result.warnings = list(dict.fromkeys(result.warnings))
    result.latency_ms = (time.perf_counter()-started)*1000
    return result
