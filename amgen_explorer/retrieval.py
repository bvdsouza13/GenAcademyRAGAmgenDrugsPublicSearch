"""Scope-pinned retrieval; cloud matches must resolve to immutable local records."""
from __future__ import annotations
from pathlib import Path
from .models import EvidenceBundle
from .indexing import guard_text, manifest_records
from .connectivity import DocumentsClient
from .eligibility import policy_for, BULK_POLICY

SAFETY_WORDS = ("warning", "safe", "safety", "contraindicat", "side effect", "risk", "overview", "teach", "learn", "introduction")
SAFETY_KINDS = ("warning", "precaution", "contraindicat", "boxed")


def load_records(active, config):
    return manifest_records(active, config)


def retrieve(question, product_id, active, config, document_id=None, *, client=None):
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
    if not getattr(client, "host", True):
        client.check()
    hits = client.search(namespace, question, filters, config.settings["retrieval"]["top_k"])
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
    if any(word in question.lower() for word in SAFETY_WORDS):
        safety = [r for r in scoped if any(word in (str(r.get("section_kind", "")) + " " + str(r.get("section_title", ""))).lower() for word in SAFETY_KINDS)]
        if not safety:
            empty.warnings.append("Reviewed safety sections are unavailable; this evidence cannot establish the full warning profile.")
        # Direct canonical safety lookup supplements semantic ranking.
        candidates = safety + candidates
    # A split parent retains adjacent context even when semantic top-k found
    # just one continuation. Never claim the remainder was included if the
    # evidence budget cannot contain it.
    if empty.eligibility_policy == BULK_POLICY:
        expanded=[]
        emitted=set()
        for candidate in candidates:
            parents=set(candidate.get('continuation_parent_ids',[]))
            adjacent=([r for r in scoped if parents & set(r.get('continuation_parent_ids',[]))]
                      if parents else [candidate])
            for record in sorted(adjacent,key=lambda r:r.get('continuation_index',0)):
                if record['_id'] not in emitted:
                    expanded.append(record); emitted.add(record['_id'])
        candidates=expanded
    budget = config.settings["retrieval"]["evidence_token_budget"]
    used = 0
    seen = set()
    field = config.settings["pinecone"]["text_field"]
    for record in candidates:
        content_id = ((record['document_id'], record.get('source_spans',record['_id']))
                      if empty.eligibility_policy == BULK_POLICY
                      else (record["document_id"], record.get("source_text", record[field])))
        if content_id in seen:
            continue
        seen.add(content_id)
        cost = len(record[field].encode("utf-8")) + 8
        if used + cost > budget:
            empty.warnings.append("A complete passage was omitted to respect the evidence budget; it was not truncated.")
            continue
        used += cost
        empty.passages.append({"id": record["_id"], "text": record.get("source_text", record[field]),
                               "metadata": {k: v for k, v in record.items() if k not in {"_id", field}},
                               "namespace": namespace, "xml_hash": xml_hash})
    if empty.eligibility_policy == BULK_POLICY:
        included={p['id'] for p in empty.passages}
        for record in candidates:
            if record['_id'] not in included and record.get('continuation_parent_ids'):
                empty.warnings.append('The complete continuation context could not fit in the evidence budget; inspect the full source before explanation.')
                break
        for passage in empty.passages:
            limitations=passage['metadata'].get('extraction_limitations',[])
            if limitations:
                empty.warnings.append('Source extraction/layout limitation: '+', '.join(limitations)+'. View the original PDF page.')
    return empty
