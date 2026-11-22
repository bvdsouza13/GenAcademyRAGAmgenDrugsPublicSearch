"""Byte-budgeted, topic-aware packing of complete source/context groups."""
from dataclasses import dataclass, field
import re
from .evidence_policy import continuation_groups, section_category
from .learning_policy import learning_intent

@dataclass
class EvidenceSelection:
    records: list = field(default_factory=list)
    omitted_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    complete: bool = True
    used_bytes: int = 0


def record_cost(record):
    # Indexed text includes the retrieval prefix. Source-only text would
    # undercount the same envelope used for chunking and fixed-suite evaluation.
    text = record.get('_evidence_text', record.get('chunk_text', record.get('source_text', '')))
    return len(text.encode('utf-8')) + 8


def select_evidence(question, records, ranked_ids, *, budget_bytes, intent=None) -> EvidenceSelection:
    intent = intent or learning_intent(question)
    ranked = {rid: n for n, rid in enumerate(dict.fromkeys(ranked_ids))}
    groups = continuation_groups(records)
    def section_identity(record):
        return (record.get('document_id'),record.get('document_sha256'),record.get('xml_hash'),record.get('section_id'))
    # A specific-section lesson uses its full original subsection. Highlights
    # and IFU text may mention the topic but cannot supplement an available
    # actual subsection merely because they were ranked highly.
    actual_sections = set()
    if intent in ('mechanism','indications'):
        for record in records:
            label = ' '.join(str(record.get(key,'')) for key in ('section_id','section_kind','section_title')).lower()
            supplementary = re.search(r'highlight|contents|instructions?\s*for\s*use|\bifu\b',label)
            if record.get('section_id') and not supplementary and section_category(record) == intent:
                actual_sections.add(section_identity(record))
    if actual_sections:
        groups = [group for group in groups if any(section_identity(r) in actual_sections for r in group['records'])]
    def rank(group):
        return min((ranked.get(r['_id'], len(ranked)+1) for r in group['records']), default=len(ranked)+1)
    groups.sort(key=rank)
    desired = {'overview': ('indications','mechanism','safety'), 'safety': ('safety',),
               'mechanism': ('mechanism',), 'indications': ('indications',)}.get(intent, ())
    # Reserve a complete representative for each requested topic before
    # supplementing safety context or lower-ranked semantic matches.
    ordered = []
    for topic in desired:
        group = next((g for g in groups if any(section_category(r) == topic for r in g['records'])), None)
        if group is not None and group not in ordered: ordered.append(group)
    for group in groups:
        if (actual_sections or any(r['_id'] in ranked for r in group['records'])
                or any(section_category(r) in desired for r in group['records'])) and group not in ordered:
            ordered.append(group)
    result = EvidenceSelection()
    seen = set()
    for group in ordered:
        members = sorted(group['records'], key=lambda r:r.get('continuation_index', 0))
        unique = []
        for record in members:
            identity = (record['document_id'], record.get('source_spans', record['_id']))
            if identity not in seen:
                seen.add(identity); unique.append(record)
        cost = sum(record_cost(r) for r in unique)
        if result.used_bytes + cost > budget_bytes:
            result.omitted_ids += [r['_id'] for r in unique]
            result.reasons.append('A complete passage was omitted to respect the evidence budget; it was not truncated.')
            if group['parents']:
                result.reasons.append('The complete continuation context could not fit in the evidence budget; inspect the full source before explanation.')
                result.complete = False
            if actual_sections or any(section_category(r) in desired for r in unique):
                result.reasons.append('Required context for the requested source topics was omitted; inspect the full source before explanation.')
                result.complete = False
            continue
        result.records += unique; result.used_bytes += cost
    result.reasons = list(dict.fromkeys(result.reasons))
    return result
