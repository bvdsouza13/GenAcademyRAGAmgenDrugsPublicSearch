"""Complete groups and topic allocation use the indexed UTF-8 envelope."""
from copy import deepcopy
import pytest
from amgen_explorer.evidence_selection import select_evidence
from amgen_explorer.evidence_policy import assess_evidence
from test_teaching import evidence


def record(rid, kind, *, body='Synthetic source passage with its population and limitation.', prefix=''):
    return {'_id':rid,'document_id':'doc','document_sha256':'sha','xml_hash':'xml',
            'section_kind':kind,'section_title':kind,'source_text':body,'chunk_text':prefix+body}


def test_atomic_continuation_group_cannot_spend_budget_on_one_sibling():
    records = [record('a', 'mechanism'), record('b', 'mechanism')]
    for i, r in enumerate(records):
        r.update(continuation_parent_ids=['parent'], continuation_count=2, continuation_index=i)
    limited = select_evidence('Explain mechanism', records, ['a'], budget_bytes=80, intent='mechanism')
    assert limited.records == []
    assert set(limited.omitted_ids) == {'a','b'}
    assert not limited.complete and any('continuation context' in r for r in limited.reasons)
    full = select_evidence('Explain mechanism', records, ['a'], budget_bytes=200, intent='mechanism')
    assert [r['_id'] for r in full.records] == ['a','b']
    assert full.complete


def test_required_topics_keep_qualifiers_instead_of_warning_starvation():
    body = 'Synthetic text. ' * 40 + 'Only for the studied population; not established elsewhere.'
    records = [record(f'w{i}', 'warning', body=body) for i in range(8)]
    records += [record('approved', 'indications', body=body), record('how', 'mechanism', body=body)]
    chosen = select_evidence('Overview of approved uses and mechanism', records, ['approved','how'], budget_bytes=2500, intent='overview')
    assert {r['_id'] for r in chosen.records} >= {'approved','how','w0'}
    assert all(r['source_text'].endswith('not established elsewhere.') for r in chosen.records)
    assert not chosen.complete  # The omitted warnings cannot establish a complete profile.


def test_indexed_prefix_and_utf8_bytes_count_toward_complete_packing():
    r = record('a','mechanism',body='é'*20,prefix='Scope: synthetic source\n')
    assert select_evidence('mechanism',[r],['a'],budget_bytes=50,intent='mechanism').records == []
    chosen = select_evidence('mechanism',[r],['a'],budget_bytes=100,intent='mechanism')
    assert chosen.used_bytes == 72  # 24 prefix + 40 source + 8 envelope bytes.
    assert chosen.records == [r]


def test_explicit_required_context_omission_blocks_both_consumers(evidence):
    evidence.warnings = ['Required context for the requested source topics was omitted.']
    result = assess_evidence(evidence)
    assert not result.generation_eligible and not result.quiz_eligible
    assert 'missing_required_context' in result.reasons


def bundle_from_selection(selection):
    from amgen_explorer.models import EvidenceBundle
    return EvidenceBundle('Explain mechanism','medicine','ns','xml',[
        {'id':r['_id'],'text':r['source_text'],'metadata':{**r,'product_id':'medicine','section_id':r.get('section_id','12.1'),
            'page_start':1,'page_end':1,'review_state':'accepted'},'namespace':'ns'} for r in selection.records],warnings=selection.reasons)


@pytest.mark.parametrize('intent,title,section', [('mechanism','Mechanism of action','12.1'), ('indications','Indications and usage','1')])
def test_actual_section_does_not_import_unrelated_ranked_layout_tables(intent,title,section):
    actual = record('actual',intent);actual.update(section_id=section,section_title=title)
    highlights = record('highlights','highlights');highlights.update(section_id='highlights',section_title='Highlights and contents',extraction_limitations=['unresolved_table'])
    ifu = record('ifu','instructionsForUse');ifu.update(section_id='ifu',section_title='Instructions for Use',extraction_limitations=['unresolved_table'])
    selection = select_evidence('Explain '+intent,[highlights,actual,ifu],['highlights','actual','ifu'],budget_bytes=4000,intent=intent)
    assert [r['_id'] for r in selection.records] == ['actual']
    assert assess_evidence(bundle_from_selection(selection)).generation_eligible


def test_same_section_layout_and_continuation_qualifier_never_disappear():
    clean = record('clean','mechanism');clean.update(section_id='12.1',section_title='Mechanism of action')
    restricted = record('qualifier','warning',body='Mechanism qualifier and limitation in the same original subsection.')
    restricted.update(section_id='12.1',section_title='Mechanism of action',extraction_limitations=['unresolved_table'])
    for i,r in enumerate((clean,restricted)):
        r.update(continuation_parent_ids=['mechanism-parent'],continuation_count=2,continuation_index=i)
    selection = select_evidence('Explain mechanism',[clean,restricted],['clean'],budget_bytes=4000,intent='mechanism')
    assert [r['_id'] for r in selection.records] == ['clean','qualifier']
    assessment = assess_evidence(bundle_from_selection(selection))
    assert not assessment.generation_eligible and 'layout_limitation' in assessment.reasons


def test_missing_actual_section_preserves_ranked_fallback_limitations():
    fallback = record('highlight','highlights');fallback.update(section_id='highlights',section_title='Highlights and contents',extraction_limitations=['unresolved_table'])
    selection = select_evidence('Explain mechanism',[fallback],['highlight'],budget_bytes=4000,intent='mechanism')
    assert [r['_id'] for r in selection.records] == ['highlight']
    assert not assess_evidence(bundle_from_selection(selection)).generation_eligible


def test_unranked_same_mechanism_section_restriction_is_required_context():
    clean = record('clean','mechanism');clean.update(section_id='12.1',section_title='Mechanism of action')
    qualifier = record('qualifier','warning',body='The mechanism has not been established in the stated population.')
    qualifier.update(section_id='12.1',section_title='Mechanism of action',extraction_limitations=['unresolved_table'])
    selection = select_evidence('Explain mechanism',[clean,qualifier],['clean'],budget_bytes=4000,intent='mechanism')
    assert {r['_id'] for r in selection.records} == {'clean','qualifier'}
    assert not assess_evidence(bundle_from_selection(selection)).generation_eligible
    limited = select_evidence('Explain mechanism',[clean,qualifier],['clean'],budget_bytes=80,intent='mechanism')
    assert not limited.complete and any('Required context' in r for r in limited.reasons)

@pytest.mark.parametrize('question', ['Teach me the mechanism of action.', 'How does this medicine work?', 'I want to learn about approved uses.'])
def test_learning_preamble_does_not_turn_specific_section_into_broad_overview(question):
    topic = 'indications' if 'approved uses' in question else 'mechanism'
    actual = record('actual',topic);actual.update(section_id='12.1' if topic=='mechanism' else '1')
    unrelated = record('highlight','highlights');unrelated.update(section_id='highlights',extraction_limitations=['unresolved_table'])
    selection = select_evidence(question,[actual,unrelated],['actual','highlight'],budget_bytes=4000)
    assert [r['_id'] for r in selection.records] == ['actual']
