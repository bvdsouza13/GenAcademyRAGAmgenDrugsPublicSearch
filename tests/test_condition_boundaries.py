"""The last evidence boundary protects generation, source fallback and quizzes."""
import copy
import pytest

from amgen_explorer.connectivity import ProviderError
from amgen_explorer.teaching import teach, make_quiz
from test_teaching import config, evidence, FakeAI


def treatment_bundle(evidence, *, supportive=False):
    result=copy.deepcopy(evidence)
    result.question='What can treat migraine?'
    passage=result.passages[0]
    passage['text']=('AIMOVIG is indicated for the preventive treatment of migraine in adults.' if supportive
                     else 'Migraine was reported as an adverse reaction in patients receiving AIMOVIG.')
    passage['metadata'].update(product_name='AIMOVIG',section_id='section-1' if supportive else 'section-6',
        section_title='1 INDICATIONS AND USAGE' if supportive else '6 ADVERSE REACTIONS')
    return result


@pytest.mark.parametrize('layout_limited',[False,True])
def test_incidental_condition_cannot_reach_generation_or_source_fallback(config,evidence,layout_limited):
    bundle=treatment_bundle(evidence)
    # Older saved evidence can have a generic question; the actual new question governs.
    bundle.question='What is described?'
    if layout_limited:bundle.passages[0]['metadata']['extraction_limitations']=['unresolved_table']
    ai=FakeAI(bundle)
    response=teach('What can treat migraine?',bundle,config,client=ai)
    assert response.abstained and not response.citations
    assert not ai.calls
    assert bundle.passages[0]['text'] not in response.answer


def test_quiz_rejects_incidental_treatment_context(config,evidence):
    quiz=make_quiz(treatment_bundle(evidence),config)
    assert 'error' in quiz and 'choices' not in quiz


def test_valid_treatment_source_fallback_preserves_population_and_prevention(config,evidence):
    bundle=treatment_bundle(evidence,supportive=True)
    class Offline:
        def generate(self,*args,**kwargs):raise ProviderError('OpenAI',503)
    response=teach(bundle.question,bundle,config,client=Offline())
    assert response.abstained and len(response.citations)==1
    assert bundle.passages[0]['text'] in response.answer
    assert response.usage['source_fallback'] is True
    quiz=make_quiz(bundle,config)
    assert quiz['choices'][quiz['correct_index']]==bundle.passages[0]['text']


def test_mixed_old_context_cannot_reintroduce_incidental_treatment_sources(config,evidence):
    bundle=treatment_bundle(evidence,supportive=True)
    unrelated=treatment_bundle(evidence).passages[0]
    unrelated['id']='incidental';bundle.passages.append(unrelated)
    ai=FakeAI(bundle)
    response=teach(bundle.question,bundle,config,client=ai)
    assert response.abstained and not response.citations and not ai.calls


def test_generic_named_use_requires_and_accepts_pinned_catalog(config,evidence):
    from pathlib import Path
    from amgen_explorer.models import Corpus, Product
    bundle=treatment_bundle(evidence,supportive=True)
    bundle.passages[0]['text']='Erenumab is indicated for the preventive treatment of migraine in adults.'
    # Metadata alone identifies the brand, and must not invent a generic alias.
    assert 'error' in make_quiz(bundle,config)
    corpus=Corpus(Path('pinned.xml'),bundle.xml_hash,
                  [Product(bundle.product_id,'AIMOVIG',generic_name='erenumab')],[],[])
    quiz=make_quiz(bundle,config,corpus=corpus)
    assert quiz['choices'][quiz['correct_index']]==bundle.passages[0]['text']


def test_malformed_retained_continuation_abstains_instead_of_crashing(config,evidence):
    bundle=treatment_bundle(evidence,supportive=True)
    first=bundle.passages[0]
    first['metadata'].update(continuation_parent_ids=['parent'],continuation_count=2,continuation_index=0)
    second=copy.deepcopy(first);second['id']='c2';second['metadata']['continuation_index']='1'
    bundle.passages.append(second)
    ai=FakeAI(bundle)
    response=teach(bundle.question,bundle,config,client=ai)
    assert response.abstained and not ai.calls
    assert 'error' in make_quiz(bundle,config)


def grouped_treatment_bundle(evidence, *, heading=False):
    bundle=treatment_bundle(evidence,supportive=True)
    first=bundle.passages[0]
    second=copy.deepcopy(first);second['id']='c2'
    if heading:
        bundle.question='What treats macular degeneration?'
        first['text']='PAVBLU is indicated for the treatment of:'
        first['metadata'].update(product_name='PAVBLU',section_id='doc-section-1-preamble')
        second['text']='1.1 Neovascular (Wet) Age-Related Macular Degeneration (AMD)'
        second['metadata'].update(product_name='PAVBLU',section_id='doc-section-1-1',
                                  section_title=second['text'])
    else:
        first['text']='AIMOVIG is indicated for the preventive treatment of migraine'
        second['text']='in adults.'
        for index,passage in enumerate((first,second)):
            passage['metadata'].update(continuation_parent_ids=['parent'],
                                       continuation_count=2,continuation_index=index)
    bundle.passages.append(second)
    return bundle


@pytest.mark.parametrize('failure',['outage','abstained','empty','verification'])
def test_fallback_preserves_complete_condition_group(config,evidence,failure):
    bundle=grouped_treatment_bundle(evidence)
    class FailedExplanation:
        def generate(self,instructions,content,schema,name='medicine_teaching'):
            if failure=='outage':raise ProviderError('OpenAI',503)
            if name=='evidence_entailment':return {'supported':False},{}
            claims=([{'source_id':'c1','quote':bundle.passages[0]['text'],
                      'text':'AIMOVIG is indicated for the preventive treatment of migraine.'}]
                    if failure=='verification' else [])
            return {'abstained':failure=='abstained','claims':claims,'followups':[]},{}
    response=teach(bundle.question,bundle,config,client=FailedExplanation())
    assert response.abstained and response.usage['source_fallback']
    assert [citation['source_id'] for citation in response.citations]==['c1','c2']
    assert [citation['supporting_quote'] for citation in response.citations]==[
        'AIMOVIG is indicated for the preventive treatment of migraine','in adults.']
    assert '> in adults.' in response.answer and '[2]' in response.answer


def test_layout_fallback_keeps_linked_indication_predicate(config,evidence):
    bundle=grouped_treatment_bundle(evidence,heading=True)
    bundle.passages[1]['metadata']['extraction_limitations']=['unresolved_table']
    ai=FakeAI(bundle)
    response=teach(bundle.question,bundle,config,client=ai)
    assert response.abstained and not ai.calls and response.usage['source_fallback']
    assert [citation['source_id'] for citation in response.citations]==['c1','c2']
    assert '> PAVBLU is indicated for the treatment of:' in response.answer
    assert '> 1.1 Neovascular (Wet) Age-Related Macular Degeneration (AMD)' in response.answer
    assert response.citations[1]['extraction_limitations']==['unresolved_table']


@pytest.mark.parametrize('heading',[False,True])
def test_quiz_does_not_present_fragment_of_required_condition_group(config,evidence,heading):
    quiz=make_quiz(grouped_treatment_bundle(evidence,heading=heading),config)
    assert 'error' in quiz and 'choices' not in quiz and 'correct_index' not in quiz


def test_generation_and_verification_preserve_required_context_and_citations(config,evidence):
    bundle=grouped_treatment_bundle(evidence)
    class CompleteExplanation:
        def generate(self,instructions,content,schema,name='medicine_teaching'):
            if name=='evidence_entailment':
                group=content['claims'][0]['required_source_group']
                assert [(part['source_id'],part['text']) for part in group]==[
                    ('c1','AIMOVIG is indicated for the preventive treatment of migraine'),
                    ('c2','in adults.')]
                return {'supported':True},{}
            assert content['required_source_groups']==[['c1','c2']]
            return {'abstained':False,'claims':[{
                'text':'AIMOVIG is indicated for the preventive treatment of migraine in adults.',
                'source_id':'c1','quote':bundle.passages[0]['text']}],'followups':[]},{}
    response=teach(bundle.question,bundle,config,client=CompleteExplanation())
    assert not response.abstained and response.usage['explanation_verified']
    assert [citation['source_id'] for citation in response.citations]==['c1','c2']
    assert response.citations[1]['supporting_quote']=='in adults.'
    assert '[1]' in response.answer and '[2]' in response.answer


def test_verifier_receives_validated_context_to_resolve_cross_passage_references(config,evidence):
    bundle=copy.deepcopy(evidence)
    bundle.question='What mechanism of action does the source describe?'
    bundle.passages[0]['text']='The source discusses the disorders CGD and SMO.'
    second=copy.deepcopy(bundle.passages[0]);second['id']='c2'
    second['text']='In both disorders, the exact mechanism of the treatment effect has not been established.'
    bundle.passages.append(second)
    class ReferenceAware:
        def generate(self,instructions,content,schema,name='medicine_teaching'):
            if name=='evidence_entailment':
                context=content.get('scoped_context',[])
                assert {p['source_id'] for p in context}=={'c1','c2'}
                assert context[0]['text']==bundle.passages[0]['text']
                return {'supported':True},{}
            return {'abstained':False,'claims':[{'source_id':'c2','quote':second['text'],
               'text':'The exact mechanism of the treatment effect in CGD and SMO has not been established.'}], 'followups':[]},{}
    response=teach(bundle.question,bundle,config,client=ReferenceAware())
    assert not response.abstained and response.usage['explanation_verified'] is True
