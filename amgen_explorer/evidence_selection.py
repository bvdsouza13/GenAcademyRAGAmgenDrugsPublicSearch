"""Byte-budgeted, topic-aware packing of complete source/context groups."""
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
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


@dataclass
class ConditionContext:
    active: bool = False
    records: list = field(default_factory=list)
    ranked_ids: list[str] = field(default_factory=list)
    required_groups: list[list[str]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def condition_context(question, records, corpus=None, *, product_id=None, primary_only=False):
    """Select complete use-evidence groups from already validated records.

    A pinned corpus supplies brand/generic identities. Direct consumers without
    one can use consistent ``product_name`` metadata only; missing or ambiguous
    names fail closed for use questions. No identity is inferred from a slug.
    The caller retains responsibility for source/scope integrity validation.
    """
    from .query_intent import analyze_query
    from .condition_evidence import treatment_scores, treatment_evidence_groups
    if corpus is None:
        names = {}
        for record in records:
            name = record.get('product_name')
            if isinstance(name, str) and name.strip():
                names.setdefault(record.get('product_id'), set()).add(name)
        corpus = SimpleNamespace(products=[SimpleNamespace(id=pid, name=next(iter(values)), generic_name='')
            for pid, values in names.items() if pid and len(values)==1])
    intent = analyze_query(question, corpus)
    if not intent.treatment_intent:
        return ConditionContext(records=records)
    if product_id and not intent.product_candidates:
        intent = replace(intent, product_candidates=[product_id])
    products = {product.id:product for product in corpus.products}
    scores = treatment_scores(records, intent, products)
    groups = treatment_evidence_groups(records, intent, products)
    # A complete actual indication answers a use question without unrelated
    # Highlights/study supplements. Keep all required primary fragments and
    # their limitations; never filter away a flag on the primary evidence.
    if primary_only and any(score == 6 for score in scores.values()):
        groups = [group for group in groups if all(scores[rid] == 6 for rid in group)]
    positions = {record['_id']:i for i,record in enumerate(records)}
    groups.sort(key=lambda ids:(-max((scores.get(rid,0) for rid in ids),default=0),
                                min((positions[rid] for rid in ids),default=len(records))))
    wanted = list(dict.fromkeys(rid for group in groups for rid in group))
    by_id = {record['_id']:record for record in records}
    return ConditionContext(True, [by_id[rid] for rid in wanted], wanted, groups,
        [] if wanted else ['No matching treatment-use evidence was found in the selected source scope.'])


def record_cost(record):
    # Indexed text includes the retrieval prefix. Source-only text would
    # undercount the same envelope used for chunking and fixed-suite evaluation.
    text = record.get('_evidence_text', record.get('chunk_text', record.get('source_text', '')))
    return len(text.encode('utf-8')) + 8


def select_evidence(question, records, ranked_ids, *, budget_bytes, intent=None,
                    required_groups=None) -> EvidenceSelection:
    intent = intent or learning_intent(question)
    ranked = {rid: n for n, rid in enumerate(dict.fromkeys(ranked_ids))}
    groups = continuation_groups(records)
    record_ids = {record['_id'] for record in records}
    for required in required_groups or []:
        required = set(required)
        if not required <= record_ids:
            return EvidenceSelection(reasons=['Required context for a linked source passage is unavailable.'], complete=False)
        linked = [group for group in groups if any(record['_id'] in required for record in group['records'])]
        if len({group['scope'] for group in linked}) > 1:
            raise ValueError('Required source context cannot combine different document identities.')
        if len(required)>1:
            combined = {'scope':linked[0]['scope'], 'parents':set(), 'records':[], 'required_context':True}
            for group in linked:
                combined['parents'] |= group['parents']
                combined['records'] += group['records']
                groups.remove(group)
            groups.append(combined)
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
            if group.get('required_context') or actual_sections or any(section_category(r) in desired for r in unique):
                result.reasons.append('Required context for the requested source topics was omitted; inspect the full source before explanation.')
                result.complete = False
            continue
        result.records += unique; result.used_bytes += cost
    result.reasons = list(dict.fromkeys(result.reasons))
    return result
