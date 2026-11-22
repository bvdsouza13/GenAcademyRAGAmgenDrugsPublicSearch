"""Shared fail-closed evidence eligibility for explanation and scored quizzes."""
from dataclasses import dataclass, field
from .eligibility import validate_record_policy, policy_for

@dataclass
class EvidenceAssessment:
    sources: dict = field(default_factory=dict)
    generation_eligible: bool = False
    quiz_eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    section_kinds: set[str] = field(default_factory=set)


def section_category(record):
    text = (str(record.get('section_kind', '')) + ' ' + str(record.get('section_title', ''))).lower()
    if any(word in text for word in ('warning', 'precaution', 'contraindicat', 'boxed', 'adverse')): return 'safety'
    if 'mechanism' in text: return 'mechanism'
    if any(word in text for word in ('indication', 'usage', 'approved use')): return 'indications'
    return 'general'


def continuation_groups(records):
    """Connected continuation parents, pinned to the same physical document."""
    groups = []
    for record in records:
        parents = set(record.get('continuation_parent_ids') or [])
        scope = (record.get('document_id'), record.get('document_sha256'), record.get('xml_hash'))
        matches = [g for g in groups if parents and g['scope'] == scope and g['parents'] & parents]
        group = {'scope': scope, 'parents': parents, 'records': [record]}
        for other in matches:
            group['parents'] |= other['parents']; group['records'] += other['records']; groups.remove(other)
        groups.append(group)
    return groups


def incomplete_continuations(sources):
    records = [p['metadata'] for p in sources.values()]
    for group in continuation_groups(records):
        if not group['parents']: continue
        members = group['records']
        count = members[0].get('continuation_count')
        if type(count) is not int or count < 1 or len(members) != count: return True
        indices = [r.get('continuation_index') for r in members]
        if any(type(i) is not int for i in indices) or set(indices) != set(range(count)): return True
        if any(r.get('continuation_count') != count or set(r.get('continuation_parent_ids') or []) != group['parents'] for r in members): return True
    return False


def assess_evidence(evidence) -> EvidenceAssessment:
    result = EvidenceAssessment()
    try:
        policy = policy_for(evidence)
    except ValueError:
        result.reasons.append('invalid_source'); return result
    for passage in evidence.passages:
        try:
            metadata = passage['metadata']
            validate_record_policy(metadata, policy, evidence.eligibility_fingerprint)
            if (metadata.get('product_id') != evidence.product_id or metadata.get('xml_hash') != evidence.xml_hash
                    or passage.get('xml_hash', evidence.xml_hash) != evidence.xml_hash
                    or passage.get('namespace', evidence.namespace) != evidence.namespace
                    or passage.get('run_id', evidence.run_id) != evidence.run_id
                    or metadata.get('run_id', evidence.run_id) != evidence.run_id
                    or not all(metadata.get(k) for k in ('document_id','document_sha256','section_id','page_start','page_end'))
                    or not isinstance(passage.get('text'), str) or not passage['text'].strip()
                    or ('source_text' in metadata and metadata['source_text'] != passage['text'])
                    or passage['id'] in result.sources):
                raise ValueError()
            result.sources[passage['id']] = passage
            result.section_kinds.add(section_category(metadata))
        except (ValueError, KeyError, TypeError):
            result.reasons.append('invalid_source')
    if not result.sources: result.reasons.append('no_sources')
    if len({(p['metadata']['document_id'],p['metadata']['document_sha256']) for p in result.sources.values()}) > 1:
        result.reasons.append('multiple_documents')
    if any(p['metadata'].get('extraction_limitations') for p in result.sources.values()):
        result.reasons.append('layout_limitation')
    if incomplete_continuations(result.sources) or any('continuation context' in w.lower() for w in evidence.warnings):
        result.reasons.append('incomplete_continuations')
    if any('required context' in w.lower() for w in evidence.warnings): result.reasons.append('missing_required_context')
    result.reasons = list(dict.fromkeys(result.reasons))
    result.generation_eligible = result.quiz_eligible = not result.reasons
    return result
