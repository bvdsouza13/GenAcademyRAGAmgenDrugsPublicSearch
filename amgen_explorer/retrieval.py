"""Scope-pinned retrieval; cloud matches must resolve to immutable local records."""
from __future__ import annotations
import json
from .models import EvidenceBundle
from .indexing import guard_text, manifest_records
from .connectivity import DocumentsClient, ProviderError
from scripts.setup_pinecone import SetupError
from .evidence_selection import select_evidence
from .learning_policy import learning_intent
from .eligibility import policy_for, BULK_POLICY

SAFETY_WORDS = ("warning", "safe", "safety", "contraindicat", "side effect", "risk", "overview", "teach", "learn", "introduction")
SAFETY_KINDS = ("warning", "precaution", "contraindicat", "boxed")


def load_records(active, config):
    return manifest_records(active, config)


def retrieve(question, product_id, active, config, document_id=None, *, client=None, corpus=None):
    namespace = (active or {}).get("namespace", "")
    xml_hash = (active or {}).get("xml_hash", "")
    empty = EvidenceBundle(question, product_id, namespace, xml_hash, [],
                           eligibility_policy=policy_for(active or {}),
                           eligibility_fingerprint=(active or {}).get('eligibility_fingerprint',''),
                           run_id=(active or {}).get('run_id',''))
    if not active or active.get("status") != "verified":
        empty.warnings.append("No verified corpus is active. Review, load and publish sources first.")
        return empty
    records = load_records(active, config)
    if product_id not in active.get("product_ids", []):
        empty.warnings.append("This medicine has no reviewed evidence in the active corpus.")
        return empty
    guard_text(question)
    scoped = [r for r in records if r.get("product_id") == product_id and r.get("xml_hash") == xml_hash
              and (document_id is None or r.get("document_id") == document_id)]
    if not scoped:
        empty.warnings.append("No reviewed evidence is available for this product/document scope.")
        return empty
    docs = {r["document_id"] for r in scoped}
    if len(docs) > 1:
        empty.warnings.append("This medicine has multiple source documents or device scopes. Select one source document before asking.")
        return empty
    filters = {"$and": [{"product_id": {"$eq": product_id}}, {"xml_hash": {"$eq": xml_hash}},
                        {"document_id": {"$eq": next(iter(docs))}}]}
    client = client or DocumentsClient(config)
    try:
        if not getattr(client, "host", True):
            client.check()
        hits = client.search(namespace, question, filters, config.settings["retrieval"]["top_k"])
    except (ProviderError, SetupError, OSError):
        # Never re-enter global/semantic search after its provider failed.
        from .search import search_local
        if corpus is None and (active.get('search_artifact') or empty.eligibility_policy == BULK_POLICY):
            import hashlib
            from .xml_store import load_corpus
            snapshot = config.path('corpus_dir') / xml_hash / 'AmgenProducts.xml'
            if not snapshot.is_file() or hashlib.sha256(snapshot.read_bytes()).hexdigest() != xml_hash:
                raise ValueError('The pinned XML snapshot is unavailable or changed.')
            corpus = load_corpus(snapshot)
        local = search_local(question, active, config, corpus,
                             product_ids=[product_id], document_ids=sorted(docs),
                             limit=min(100, max(20, config.settings['retrieval']['top_k'])))
        expected_local = {r['_id']:r for r in scoped}
        field = config.settings['pinecone']['text_field']
        hits = []
        for hit in local.hits:
            record = expected_local.get(hit.get('id')) if isinstance(hit,dict) else None
            valid = record is not None
            if valid:
                metadata = hit.get('metadata', {})
                if not isinstance(metadata,dict):
                    empty.warnings.append('A malformed local search hit was excluded.')
                    continue
                valid = (hit.get('run_id') == empty.run_id and hit.get('namespace') == namespace
                         and hit.get('xml_hash') == xml_hash
                         and hit.get('text') == record.get('source_text',record[field])
                         and isinstance(metadata,dict))
                for key,value in record.items():
                    if key in {'_id',field}: continue
                    if key == 'source_spans':
                        value = json.loads(value) if isinstance(value,str) else value
                    if metadata.get(key) != value: valid = False
            if valid:
                hits.append(record)
            else:
                empty.warnings.append('A local hit failed pinned source/scope verification and was excluded.')
        empty.warnings.append('Semantic search is unavailable. Showing verified scoped local evidence only (degraded mode).')
        empty.warnings.extend(local.warnings)
    expected = {r["_id"]: r for r in scoped}
    candidates = []
    for hit in hits:
        if not isinstance(hit, dict):
            empty.warnings.append("A malformed search hit was excluded.")
            continue
        record = expected.get(hit.get("_id"))
        if record is None or any(hit.get(k) != v for k, v in record.items()):
            empty.warnings.append("A search hit failed active source/scope verification and was excluded.")
            continue
        candidates.append(record)
    intent = learning_intent(question)
    if intent in ('overview', 'safety') and not any(
            any(word in (str(r.get('section_kind',''))+' '+str(r.get('section_title',''))).lower()
                for word in SAFETY_KINDS) for r in scoped):
        empty.warnings.append('Reviewed safety sections are unavailable; this evidence cannot establish the full warning profile.')
    if not candidates and intent not in ('overview', 'safety'):
        return empty
    field = config.settings['pinecone']['text_field']
    selection = select_evidence(question, [{**r, '_evidence_text': r[field]} for r in scoped],
                                [r['_id'] for r in candidates],
                                budget_bytes=config.settings['retrieval']['evidence_token_budget'], intent=intent)
    empty.warnings.extend(selection.reasons)
    for record in selection.records:
        empty.passages.append({'id': record['_id'], 'text': record.get('source_text', record[field]),
                               'metadata': {k:v for k,v in record.items() if k not in {'_id', field, '_evidence_text'}},
                               'namespace': namespace, 'xml_hash': xml_hash, 'run_id': empty.run_id})
        limitations = record.get('extraction_limitations', [])
        if limitations:
            empty.warnings.append('Source extraction/layout limitation: '+', '.join(limitations)+'. View the original PDF page.')
    return empty
