"""Conservative discovery of source-supported uses, without generated claims.

This is a finite textual relation check, not a clinical knowledge base. Unknown
phrasing and fragments without a named subject are omitted. Original text,
qualifiers, layout flags and source coordinates are never changed.
"""
import re

from .query_intent import condition_word, tokens, TREATMENT_WORDS, FILLER


_NEGATIVE = re.compile(
    r'\b(?:not|never)\s+(?:(?:been|be|being|currently|yet|specifically|clinically)\s+)*'
    r'(?:indicated|approved|recommended|used|effective|established|demonstrated|evaluated)|'
    r'\b(?:do|does|did|should|must|can|may)\s+not\b|\bnot\s+(?:for|to)\b|'
    r'\b(?:no\s+(?:clinical\s+)?(?:benefit|efficacy)|failed\s+to)\b')
_DIRECT = re.compile(
    r'^(?:(?:is|are|was|were)\s+(?:(?:a|an)\s+[^.!?;]{0,100}?\s+)?'
    r'(?:indicated|approved|used)\b|'
    r'(?:can|may)\s+(?:be\s+used\s+)?(?:to\s+)?(?:treat|prevent)\b|'
    r'(?:treats?|prevents?)\b)')
_RELATION = re.compile(r'\b(?:treat(?:s|ing|ment)?|prevent(?:s|ing|ion|ive|ative)?|indicated|approved|used\s+(?:for|to))\b')
_QUALIFIER_BOUNDARY = re.compile(r'\b(?:but|however|although|whereas|except|excluding)\b|\brather\s+than\b|,\s*not\b|\band\s+(?:may|can|could|might|does|did|not)\b')


def _section(record):
    heading = ' '.join(str(record.get('section_title','')).casefold().split())
    section_id = str(record.get('section_id',''))
    if 'contraindication' in heading:
        return None
    if ('indications and usage' in heading or re.match(r'^1(?:\.\d+)?\s', heading)
            or re.search(r'-section-1(?:-|$)', section_id)):
        return 'indication'
    if any(x in heading for x in ('medication guide','patient information')):
        return 'patient'
    if 'highlights' in heading:
        return 'highlights'
    if 'clinical studies' in heading or re.match(r'^14(?:\.\d+)?\s', heading) or re.search(r'-section-14(?:-|$)',section_id):
        return 'study'
    return None


def _aliases(product):
    if product is None:
        return []
    return [r'\b' + r'\s+'.join(map(re.escape,tokens(value))) + r'\b'
            for value in (product.name, product.generic_name) if tokens(value)]


def treatment_relevance(record, intent, product, *, allow_study=False):
    """Return qualifying source tier; clinical studies need a direct-use anchor."""
    if intent.treatment_intent == 'negative_use':
        return False, 0
    if not intent.condition_terms and not intent.product_candidates:
        return False, 0
    if intent.product_candidates and record['product_id'] not in intent.product_candidates:
        return False, 0
    kind = _section(record)
    if kind is None or (kind == 'study' and not allow_study):
        return False, 0
    aliases = _aliases(product)
    if not aliases:
        return False, 0
    text = ' '.join(str(record.get('source_text','')).split()).casefold()
    # Conditions and positive relations must occur in the same sentence; a
    # nearby warning or concomitant medicine cannot supply the condition.
    for clause in re.split(r'[.!?;]\s+', text):
        if _NEGATIVE.search(clause):
            continue
        for alias in aliases:
            for subject in re.finditer(alias, clause):
                tail = clause[subject.end():].lstrip(' ®™(),-')
                # This modifier belongs to the named product's use predicate;
                # retain it in original evidence while recognizing the subject.
                tail = re.sub(r'^in\s+combination\s+with\s+[^.!?;]{1,100}?,\s*(?=(?:is|are|was|were)\b)','',tail)
                direct = bool(_DIRECT.match(tail))
                clinical = (kind == 'study' and 'efficacy' in clause[:subject.start()]
                            and bool(re.match(r'(?:was|were|has been|have been)\s+(?:evaluated|demonstrated|established)',tail)))
                relation = _RELATION.search(tail)
                # The condition must be the object of this product's asserted
                # use, not a preceding patient history or a later side effect.
                target = _QUALIFIER_BOUNDARY.split(tail[relation.end():],maxsplit=1)[0] if relation else ''
                # Another grammatical subject owns its own assertion. Do not
                # attribute that medicine's indication to this subject.
                target = re.split(r'\band\s+(?:[\w-]+\s+){1,6}(?:is|are|was|were)\b',target,maxsplit=1)[0]
                # A second use predicate can have different acute/preventive
                # or population qualifiers. Omit ambiguous coordinated uses
                # instead of borrowing a qualifier from another indication.
                if re.search(r'\b(?:and|or)\s+(?:(?:for|the|acute|preventive)\s+)*(?:treat(?:s|ment)?|prevent(?:s|ion)?)\b', target):
                    continue
                # Patients receiving a therapy are not evidence that this
                # product treats that therapy's target disease (e.g. bone-mass
                # support or infection prevention during cancer treatment).
                target = re.split(r'\b(?:receiving|undergoing|during)\b|\btreated\s+with\b|\b(?:previously|formerly)\s+(?:received|treated|used)\b|\b(?:due\s+to|caused\s+by|associated\s+with)\b', target, maxsplit=1)[0]
                # An explicit object followed by a patient comorbidity is not
                # a second indication. "Treatment of patients with ..." is
                # patient-first and stays intact. Source statements explicitly
                # targeting signs and symptoms can name the disease in their
                # patient clause; no such inference is made for other goals.
                symptom_goal = bool(re.search(r'\breduc(?:e|ing)\s+signs\s+and\s+symptoms\b', target))
                if not symptom_goal:
                    target = re.split(r'\bin\s+(?:(?:adult|pediatric)\s+)?patients?\s+with\b',target,maxsplit=1)[0]
                body = {condition_word(w) for w in tokens(target)}
                if not set(intent.condition_terms) <= body:
                    continue
                if not (body - TREATMENT_WORDS - FILLER):
                    continue
                if intent.treatment_intent == 'prevention' and not re.search(r'\bprevent\w*\b',tail[:relation.end()] + target):
                    continue
                if intent.treatment_intent == 'acute_treatment' and not re.search(r'\b(?:acute|abortive)\b',target):
                    continue
                if (direct or clinical) and relation:
                    return True, {'indication':6,'highlights':5,'patient':4,'study':2}[kind]
    return False, 0


def _scope(record):
    return tuple(record.get(key) for key in ('product_id','document_id','document_sha256','xml_hash'))


def _source_groups(records):
    from .evidence_policy import continuation_groups, incomplete_continuations
    groups = [[record] for record in records if not record.get('continuation_parent_ids')]
    for group in continuation_groups([record for record in records if record.get('continuation_parent_ids')]):
        members = group['records']
        if group['parents'] and (incomplete_continuations({r['_id']:{'metadata':r} for r in members})
                                  or len({r.get('section_id') for r in members}) != 1):
            continue
        groups.append(sorted(members,key=lambda r:r['continuation_index']))
    # A numbered, heading-only indication can inherit an explicit colon-ended
    # Section 1 predicate, but only within its exact pinned document scope.
    for parent in records:
        if not str(parent.get('section_id','')).endswith('-section-1-preamble'):
            continue
        if not str(parent.get('source_text','')).rstrip().endswith(':'):
            continue
        prefix = parent['section_id'][:-len('preamble')]
        for child in records:
            if (_scope(parent) != _scope(child)
                    or not re.fullmatch(re.escape(prefix)+r'\d+',str(child.get('section_id','')))
                    or ' '.join(tokens(child.get('source_text',''))) != ' '.join(tokens(child.get('section_title','')))
                    or type(parent.get('page_start')) is not int or type(child.get('page_start')) is not int
                    or not 0 <= child['page_start'] - parent['page_start'] <= 1):
                continue
            groups.append([parent,child])
    return groups


def _matches(records, intent, products):
    groups = _source_groups(list(records))
    matches = []; supported_scopes = set()
    def combined(group):
        return {**group[0],'source_text':' '.join(r.get('source_text','') for r in group)}
    for group in groups:
        record = combined(group)
        eligible,tier = treatment_relevance(record,intent,products.get(record['product_id']))
        if eligible:
            matches.append((group,tier));supported_scopes.add(_scope(record))
    matched_ids = {r['_id'] for group,_ in matches for r in group}
    for group in groups:
        record = combined(group)
        if _scope(record) in supported_scopes and not all(r['_id'] in matched_ids for r in group):
            eligible,tier = treatment_relevance(record,intent,products.get(record['product_id']),allow_study=True)
            if eligible:
                matches.append((group,tier))
    return matches


def treatment_scores(records, intent, products):
    """Score validated records; products maps pinned IDs to Product objects.

    Clinical studies require a direct-use anchor in the same pinned document.
    Linked preambles and complete continuation groups are assessed atomically.
    Callers retain responsibility for immutable source validation and scope.
    """
    scores = {}
    for group,tier in _matches(records,intent,products):
        for record in group:
            scores[record['_id']] = max(tier,scores.get(record['_id'],0))
    return scores


def treatment_evidence_groups(records, intent, products):
    """Original record IDs that must remain together when packing evidence."""
    return [[r['_id'] for r in group] for group,_ in _matches(records,intent,products)]
