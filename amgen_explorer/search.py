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
from .query_intent import analyze_query, tokens, CONCEPTS, SECTIONS, TREATMENT_WORDS
from .indexing import digest, guard_text, manifest_records, validate_manifest_records
from scripts.setup_pinecone import SetupError

# Artifact bytes/paths are immutable independently of runtime ranking policy.
ARTIFACT_VERSION = 'global-rrf-v1'
RANKING_VERSION = 'intent-relevance-v3'


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
    outcome: str = 'no_results'
    suggestions: list[str] = field(default_factory=list)
    match_mode: str = 'content'


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _policy_fingerprint(run):
    # Include the complete policy pin even for legacy manifests without a marker.
    return digest({k: v for k, v in run.items() if 'policy' in k or k == 'schema_version'})


def _artifact_path(run, config):
    return config.path('manifest_dir') / (run['run_id'] + '.' + ARTIFACT_VERSION + '.sqlite')


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
            'catalog_digest':digest(catalog), 'ranking_version':ARTIFACT_VERSION,
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
    """Fail closed on stale content, path substitution or changed artifact pins."""
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


def _relevance(record, intent, product, *, semantic=False, clinical_support=False):
    """Gate on source features, never RRF or a universal provider score cutoff.

    Named overviews admit catalog matches; topical questions also rank their
    actual source/section overlap. Cross-product body matches remain eligible.
    Semantic-only candidates need a source-grounded concept/section feature.
    """
    if intent.treatment_intent:
        from .condition_evidence import treatment_relevance
        return treatment_relevance(record,intent,product,allow_study=clinical_support)
    text = record.get('source_text', '')
    body = set(tokens(text + ' ' + str(record.get('section_title', ''))))
    terms = set(intent.meaningful_terms)
    qualifiers = terms - set(intent.alias_terms)
    named = record['product_id'] in intent.product_candidates
    source_words=' '+' '.join(tokens(text))+' '
    body_reference=any(' '+alias+' ' in source_words for alias in intent.matched_aliases)
    overlap = len(qualifiers & body)
    topical_overlap = bool((qualifiers - {'not','no','never','without'}) & body)
    section_words = set(SECTIONS.get(intent.section_intent, ()))
    section = bool(section_words & set(tokens(str(record.get('section_title', '')))))
    concept = sum(bool(terms & group) and bool(body & group) for group in CONCEPTS)
    # Generic conversational words alone provide no retrieval evidence.
    relevant = bool((named and (not qualifiers or topical_overlap or section or concept))
                    or topical_overlap or (semantic and concept))
    # Overview queries intentionally browse the named product's source.
    if named and intent.section_intent == 'overview':relevant = True
    if intent.product_candidates and not qualifiers:relevant = named or body_reference
    if intent.product_candidates and not named:
        # Shared section labels (mechanism, storage, warnings) cannot make
        # another medicine relevant to a named question. Specific body terms
        # still admit cross-product discoveries such as ACTIMMUNE latex.
        specific = qualifiers - section_words - {'not','no','never','without'}
        relevant = bool(specific & body) or body_reference
    if not terms:relevant = False
    coverage = overlap / len(qualifiers) if qualifiers else 0
    return relevant, 4 * named + 3 * section + 2 * coverage + .5 * concept


def search_local(query, run, config, corpus=None, *, product_ids=None, document_ids=None, limit=20):
    """Search pinned local records without constructing or contacting a provider.

    Legacy manual-review runs may not have a catalog/artifact. They use their
    validated manifest records; full-library runs always require their artifact.
    """
    return _search(query,run,config,corpus,product_ids=product_ids,
                   document_ids=document_ids,limit=limit,local_only=True)


def search_library(query, run, config, corpus, *, client=None, product_ids=None, document_ids=None, limit=20):
    """Explicit global discovery. Original query goes unchanged to semantics."""
    return _search(query,run,config,corpus,client=client,product_ids=product_ids,
                   document_ids=document_ids,limit=limit)


def _search(query, run, config, corpus, *, client=None, product_ids=None, document_ids=None, limit=20, local_only=False):
    started = time.perf_counter()
    guard_text(query)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Search limit must be between 1 and 100.')
    if not run or run.get('status') != 'verified':
        raise ValueError('Choose a verified library version before searching.')
    for scope in (product_ids, document_ids):
        if scope is not None and (not isinstance(scope,list) or not all(isinstance(v,str) and v for v in scope)):
            raise ValueError('Search filters must be lists of source identities.')
    records = manifest_records(run, config)
    manual = local_only and corpus is None and not run.get('full_library') and not run.get('search_artifact')
    if manual:
        validate_manifest_records(run, records, config)
        artifact = payload = None
    else:
        artifact, payload = _validated_payload(run, records, config, corpus)
    result = SearchResults(query,run['run_id'],run['namespace'],run['xml_hash'])
    intent = analyze_query(query,corpus)
    result.suggestions = intent.suggestions
    result.match_mode = 'treatment_evidence' if intent.treatment_intent else 'content'
    scoped = {r['_id']:r for r in records if (product_ids is None or r['product_id'] in product_ids)
              and (document_ids is None or r['document_id'] in document_ids)}
    lexical_terms = intent.meaningful_terms
    if intent.treatment_intent:
        # Clinical verbs are intent, not retrieval anchors. Include normalized
        # condition inflections so local fallback handles e.g. migraines.
        lexical_terms = intent.condition_terms + [w for w in intent.meaningful_terms
            if w not in TREATMENT_WORDS]
    if manual:
        lexical = [rid for rid,r in scoped.items() if set(lexical_terms)&set(tokens(r.get('source_text',r[config.settings['pinecone']['text_field']])+' '+str(r.get('section_title',''))))]
    else:
        lexical = [rid for rid in _lexical_ids(payload,artifact.engine,' '.join(lexical_terms)) if rid in scoped]
    filters = [{'xml_hash':{'$eq':run['xml_hash']}}]
    if product_ids is not None:filters.append({'product_id':{'$in':sorted(set(product_ids))}})
    if document_ids is not None:filters.append({'document_id':{'$in':sorted(set(document_ids))}})
    semantic = []
    if not local_only and scoped:
        client = client or DocumentsClient(config)
        try:
            if not getattr(client,'host',True):client.check()
            candidate_count = min(100,max(limit,config.settings.get('search',{}).get('semantic_candidates',60)))
            hits = client.search(run['namespace'],query,{'$and':filters},candidate_count)
            if not isinstance(hits,list):raise ValueError('Invalid semantic result shape.')
            for hit in hits:
                expected = scoped.get(hit.get('_id')) if isinstance(hit,dict) else None
                if expected is None or any(hit.get(k)!=v for k,v in expected.items()):
                    result.warnings.append('A semantic hit failed pinned source/scope verification and was excluded.')
                    continue
                if expected['_id'] not in semantic:semantic.append(expected['_id'])
            reported = getattr(client,'last_usage',None)
            if isinstance(reported,dict):result.usage=dict(reported)
        except (ProviderError,SetupError,ValueError,OSError):
            result.degraded=True
            result.warnings.append('Semantic search is unavailable. Showing verified local text search matches only (degraded mode).')
    ranks={}
    for channel in (lexical,semantic):
        for rank,rid in enumerate(channel,1):ranks[rid]=ranks.get(rid,0)+1/(60+rank)
    field_name=config.settings['pinecone']['text_field']
    products = {p.id:p for p in corpus.products} if corpus else {}
    clinical_scores = {}
    clinical_groups = []
    if intent.treatment_intent:
        from .condition_evidence import treatment_scores, treatment_evidence_groups
        clinical_scores = treatment_scores(scoped.values(),intent,products)
        clinical_groups = treatment_evidence_groups(scoped.values(),intent,products)
    relevance={}
    for rid in ranks:
        record=scoped[rid]
        # Legacy records have source text in the configured indexed field.
        candidate={**record,'source_text':record.get('source_text',record[field_name])}
        if intent.treatment_intent:
            relevant,score = rid in clinical_scores, clinical_scores.get(rid,0)
        else:
            relevant,score=_relevance(candidate,intent,products.get(record['product_id']),semantic=rid in semantic)
        if relevant:relevance[rid]=score
    # Relevance first; document diversity only breaks equivalent relevance.
    ranked=sorted(relevance,key=lambda rid:(-relevance[rid],-ranks[rid],rid))
    chosen=[];seen_documents={}
    if intent.treatment_intent:
        # A lexical child-heading match also needs its explicit use predicate;
        # complete continuations and linked parents cannot be clipped by top-k.
        groups = [group for group in clinical_groups if any(rid in ranks for rid in group)]
        while groups and len(chosen) < limit:
            best = max(max(clinical_scores[rid] for rid in group) for group in groups)
            peers = [group for group in groups if max(clinical_scores[rid] for rid in group) == best]
            group = min(peers,key=lambda group:(seen_documents.get(scoped[group[0]]['document_id'],0),
                -sum(ranks.get(rid,0) for rid in group),tuple(group)))
            groups.remove(group)
            added = [rid for rid in group if rid not in chosen]
            if not added or len(chosen)+len(added)>limit:
                continue
            if any(_overlaps(scoped[rid],scoped[prior],field_name) for rid in added for prior in chosen):
                continue
            chosen.extend(added)
            did=scoped[group[0]]['document_id'];seen_documents[did]=seen_documents.get(did,0)+1
        ranked = []
    while ranked and len(chosen)<limit:
        best=relevance[ranked[0]]
        peers=[rid for rid in ranked if relevance[rid]==best]
        rid=min(peers,key=lambda rid:(seen_documents.get(scoped[rid]['document_id'],0),-ranks[rid],rid))
        ranked.remove(rid);record=scoped[rid]
        if any(_overlaps(record,scoped[prior],field_name) for prior in chosen):continue
        chosen.append(rid);did=record['document_id'];seen_documents[did]=seen_documents.get(did,0)+1
    catalog={r['id']:r for r in _catalog(run,records,corpus)} if not manual else {}
    groups={}
    for rid in chosen:
        record=scoped[rid]
        metadata={k:v for k,v in record.items() if k not in {'_id',field_name}}
        metadata['source_spans']=_spans(record)
        metadata['indexed_text_bytes']=len(record[field_name].encode('utf-8'))
        source=catalog.get(rid,{'product_id':record['product_id'],'document_id':record['document_id']})
        hit={'id':rid,'text':record.get('source_text',record[field_name]),'metadata':metadata,
             'run_id':run['run_id'],'namespace':run['namespace'],'xml_hash':run['xml_hash'],
             'score':ranks.get(rid,0),**{k:v for k,v in source.items() if k!='id'}}
        result.hits.append(hit)
        key=(record['product_id'],record['document_id'])
        groups.setdefault(key,{'product_id':key[0],'document_id':key[1],'hits':[]})['hits'].append(hit)
        if record.get('extraction_limitations') or record.get('layout_limitations'):
            result.warnings.append('A source has extraction/layout limitations. View its PDF page before interpreting table or figure relationships.')
    result.groups=list(groups.values())
    if intent.ambiguity or intent.needs_context or (not chosen and result.suggestions):
        result.outcome='clarification'
    elif chosen:result.outcome='results'
    result.warnings=list(dict.fromkeys(result.warnings))
    result.latency_ms=(time.perf_counter()-started)*1000
    return result
