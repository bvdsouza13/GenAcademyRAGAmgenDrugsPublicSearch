"""Condition/use discovery must not promote incidental words into indications.

Synthetic controls deliberately include misleading clinical language. Expectations
are hand selected from the text; only provider transport is faked.
"""
from dataclasses import asdict
import copy
import json
from pathlib import Path

import pytest

from amgen_explorer.connectivity import ProviderError
from amgen_explorer.indexing import manifest_records
from amgen_explorer.models import Corpus, Document, Product
from amgen_explorer.search import build_search_artifact, search_library, search_local
from test_indexing import FakeDocuments, config, plan, service


SOURCES = [
    ('aimovig', 'AIMOVIG', 'indication', '1 INDICATIONS AND USAGE',
     'AIMOVIG is indicated for the preventive treatment of migraine in adults.'),
    ('aimovig', 'AIMOVIG', 'study', '14 CLINICAL STUDIES',
     'The efficacy of AIMOVIG was evaluated as a preventive treatment of episodic or chronic migraine in three randomized studies.'),
    ('aimovig', 'AIMOVIG', 'patient', 'Patient Information',
     'AIMOVIG is a prescription medicine used for the preventive treatment of migraine in adults. It is not known if AIMOVIG is safe and effective in children under 18 years of age.'),
    ('caption', 'CAPTION', 'caption', '14 CLINICAL STUDIES', 'Intent-to-treat population.'),
    ('event', 'EVENT', 'adverse', '6.1 Clinical Trials Experience', 'Migraine was an adverse reaction in treated patients.'),
    ('event', 'EVENT', 'concomitant', '14 CLINICAL STUDIES', 'Patients receiving EVENT could take AIMOVIG to treat migraine during the study.'),
    ('event', 'EVENT', 'incidental', 'Patient Information', 'EVENT treats plaque psoriasis. Tell your doctor if you have migraine.'),
    ('negative', 'NEGATIVE', 'negative', '1 INDICATIONS AND USAGE', 'NEGATIVE is not indicated for the treatment of migraine.'),
    ('negative', 'NEGATIVE', 'unknown', '14 CLINICAL STUDIES', 'The efficacy of NEGATIVE for treating migraine has not been established.'),
    ('negative', 'NEGATIVE', 'failed', '14 CLINICAL STUDIES', 'NEGATIVE did not reduce migraine frequency when evaluated as a preventive treatment.'),
    ('asthma', 'ASTHMA', 'asthma', '1 INDICATIONS AND USAGE', 'ASTHMA is indicated for the treatment of severe asthma in adults.'),
    ('joint', 'JOINT', 'joint', '1.1 Psoriatic arthritis', 'JOINT is indicated for the treatment of active psoriatic arthritis in adults.'),
    ('joint', 'JOINT', 'rheumatoid', '6 ADVERSE REACTIONS', 'Patients with rheumatoid arthritis reported migraine.'),
    ('other', 'OTHER', 'concurrent', '14 CLINICAL STUDIES', 'Other medicines used to treat migraine were permitted in patients receiving OTHER.'),
    ('other', 'OTHER', 'safety', '5 WARNINGS AND PRECAUTIONS', 'Treat migraine as clinically appropriate during OTHER treatment.'),
    ('event', 'EVENT', 'same-sentence', '1 INDICATIONS AND USAGE', 'EVENT is indicated for the treatment of plaque psoriasis and may cause migraine.'),
    ('event', 'EVENT', 'excluded-condition', 'Patient Information', 'EVENT is used to treat plaque psoriasis, not migraine.'),
    ('event', 'EVENT', 'comorbidity', '1 INDICATIONS AND USAGE', 'In adults with migraine, EVENT is indicated for the treatment of plaque psoriasis.'),
    ('trial', 'TRIAL', 'trial-only', '14 CLINICAL STUDIES', 'The efficacy of TRIAL was evaluated as a preventive treatment of migraine in adults.'),
    ('pav', 'PAVBLU', 'parent', '1 INDICATIONS AND USAGE', 'PAVBLU is indicated for the treatment of:'),
    ('pav', 'PAVBLU', 'heading', '1.3 Diabetic Macular Edema (DME)', '1.3 Diabetic Macular Edema (DME)'),
    ('other', 'OTHER', 'latex', 'Device', 'The stopper contains natural rubber latex.'),
    ('aimovig', 'AIMOVIG', 'storage', 'Storage', 'Store AIMOVIG refrigerated at 2 to 8 degrees.'),
]


@pytest.fixture(params=[True, False], ids=['fts5', 'token-engine'])
def condition_library(config, plan, request):
    prototype = plan.chunks[0]
    products = {}; documents = {}; chunks = []
    for i, (pid, brand, cid, heading, text) in enumerate(SOURCES):
        did = pid + '-label'; sha = str(i % 10) * 64
        if did not in documents:
            documents[did] = Document(did, pid, did+'.pdf', sha, 1, '2025', '')
            products[pid] = Product(pid, brand, '', [did])
        chunk = copy.deepcopy(prototype)
        chunk.id = cid; chunk.text = text
        chunk.metadata.update(product_id=pid, document_id=did, document_sha256=documents[did].sha256,
            section_id=heading, section_title=heading, source_text=text,
            source_spans=json.dumps([{'page':1, 'start':i*1000, 'end':i*1000+len(text), 'archive_block_id':did+'-page'}]))
        if cid in ('parent','heading'):
            chunk.metadata['section_id']='pav-label-section-1-'+('preamble' if cid=='parent' else '3')
        chunks.append(chunk)
    plan.chunks = chunks
    provider = FakeDocuments()
    provider.search = lambda namespace, *args: list(provider.records.get(namespace, {}).values())
    run = service(config, provider).ingest(plan)
    records = manifest_records(run, config)
    corpus = Corpus(Path('condition.xml'), run['xml_hash'], list(products.values()), list(documents.values()), [])
    run['search_artifact'] = asdict(build_search_artifact(run, records, corpus, config, use_fts5=request.param))
    return run, records, corpus, provider


@pytest.mark.parametrize('query', ['What can treat migraine?', 'What treats migraine?', 'migraine treatment',
    'medicines for migraine', 'What can prevent migraines?', 'Which drugs are used for migraine?',
    'Is AIMOVIG approved for migraine?'])
@pytest.mark.parametrize('provider_mode', ['normal', 'outage'])
def test_treatment_queries_only_return_supporting_uses_and_rank_indication_first(config, condition_library, query, provider_mode):
    run, records, corpus, provider = condition_library
    before = list(provider.writes)
    if provider_mode == 'outage':
        def fail(*args): raise ProviderError('Pinecone', 503)
        provider.search = fail
    else:
        provider.search = lambda *args: [{**r, '_score':1000.0} for r in reversed(records)]
    result = search_library(query, run, config, corpus, client=provider)
    assert result.hits and result.hits[0]['id'] == 'indication'
    assert {h['id'] for h in result.hits} == {'indication','study','patient'}
    assert all(h['product_id'] == 'aimovig' for h in result.hits)
    assert result.hits[0]['text'] == SOURCES[0][-1]
    assert 'children under 18' in next(h['text'] for h in result.hits if h['id']=='patient')
    assert result.match_mode == 'treatment_evidence'
    assert result.degraded == (provider_mode == 'outage')
    assert provider.writes == before


@pytest.mark.parametrize('query', ['What treats unknowncondition?', 'What treats rheumatoid arthritis?',
    'What treats acute migraine?', 'What treats migraine in children?'])
def test_unsupported_conditions_population_and_acute_use_do_not_recycle_other_evidence(config, condition_library, query):
    run, _, corpus, _ = condition_library
    assert not search_local(query, run, config, corpus).hits


def test_multiword_condition_requires_the_requested_condition(config, condition_library):
    run, _, corpus, _ = condition_library
    result = search_local('What medicine treats psoriatic arthritis?', run, config, corpus)
    assert [h['id'] for h in result.hits] == ['joint']


@pytest.mark.parametrize('query',["What is AIMOVIG used for?", "What are AIMOVIG's uses?"])
def test_named_use_question_ranks_indication_without_condition_and_does_not_browse_safety(config, condition_library, query):
    run, _, corpus, _ = condition_library
    result = search_local(query, run, config, corpus)
    assert result.hits[0]['id'] == 'indication'
    assert {h['id'] for h in result.hits} == {'indication','study','patient'}


def test_explicit_filters_remain_authoritative_for_condition_discovery(config, condition_library):
    run, _, corpus, provider = condition_library
    provider.search = lambda *args: []
    assert not search_library('What can treat migraine?', run, config, corpus, client=provider, product_ids=['event']).hits
    assert {h['id'] for h in search_local('What can treat migraine?', run, config, corpus, document_ids=['aimovig-label']).hits} == {'indication','study','patient'}


def test_named_product_condition_question_requires_that_products_supporting_relation(config, condition_library):
    run, _, corpus, _ = condition_library
    assert not search_local('Can EVENT treat migraine?', run, config, corpus).hits


def test_bare_condition_and_general_content_remain_broad_discovery(config, condition_library):
    run, _, corpus, _ = condition_library
    broad = search_local('migraine', run, config, corpus)
    assert any(h['id']=='adverse' for h in broad.hits)
    assert {h['id'] for h in search_local('latex',run,config,corpus).hits} == {'latex'}
    assert search_local('AIMOVIG storage',run,config,corpus).hits[0]['id'] == 'storage'


def heading_records():
    common={'product_id':'pav','document_id':'pav-label','document_sha256':'a'*64,
            'xml_hash':'b'*64,'page_start':2,'page_end':2}
    return [
        {**common,'_id':'preamble','section_id':'pav-label-section-1-preamble',
         'section_title':'1 INDICATIONS AND USAGE','source_text':'PAVBLU is indicated for the treatment of:'},
        {**common,'_id':'child','section_id':'pav-label-section-1-3',
         'section_title':'1.3 Diabetic Macular Edema (DME)',
         'source_text':'1.3 Diabetic Macular Edema (DME)',
         'extraction_limitations':['unresolved_heading_only']},
    ]


def test_heading_use_requires_its_explicit_pinned_parent_and_keeps_the_pair():
    from amgen_explorer.condition_evidence import treatment_scores, treatment_evidence_groups
    from amgen_explorer.query_intent import analyze_query
    products={'pav':Product('pav','PAVBLU','', ['pav-label'])}
    intent=analyze_query('What treats diabetic macular edema?', None)
    records=heading_records()
    assert set(treatment_scores(records,intent,products)) == {'preamble','child'}
    assert treatment_evidence_groups(records,intent,products) == [['preamble','child']]
    assert records[1]['source_text'] == '1.3 Diabetic Macular Edema (DME)'
    assert records[1]['extraction_limitations'] == ['unresolved_heading_only']
    assert not treatment_scores(records[1:],intent,products)
    assert not treatment_scores(records[:1],intent,products)


@pytest.mark.parametrize('key,value',[('document_id','another-label'),('document_sha256','c'*64),('xml_hash','d'*64)])
def test_indication_heading_never_borrows_another_source_parent(key,value):
    from amgen_explorer.condition_evidence import treatment_scores
    from amgen_explorer.query_intent import analyze_query
    records=heading_records();records[0][key]=value
    assert not treatment_scores(records,analyze_query('What treats diabetic macular edema?',None),
                                {'pav':Product('pav','PAVBLU','',[])})


def test_complete_continuation_is_assessed_together_and_missing_member_is_rejected():
    from amgen_explorer.condition_evidence import treatment_scores, treatment_evidence_groups
    from amgen_explorer.query_intent import analyze_query
    shared={'product_id':'a','document_id':'a-label','document_sha256':'a'*64,'xml_hash':'b'*64,
            'section_id':'a-label-section-1','section_title':'1 INDICATIONS AND USAGE',
            'continuation_parent_ids':['source-passage'],'continuation_count':2}
    records=[{**shared,'_id':'first','continuation_index':0,'source_text':'ALPHA is indicated for the preventive treatment of'},
             {**shared,'_id':'second','continuation_index':1,'source_text':'migraine in adults. Not for use in children.'}]
    products={'a':Product('a','ALPHA','',[])};intent=analyze_query('What treats migraine?',None)
    assert set(treatment_scores(records,intent,products)) == {'first','second'}
    assert treatment_evidence_groups(records,intent,products)==[['first','second']]
    assert not treatment_scores(records[:1],intent,products)
    assert not treatment_scores(records[1:],intent,products)


def test_treatment_object_does_not_include_a_comorbid_condition():
    from amgen_explorer.condition_evidence import treatment_scores
    from amgen_explorer.query_intent import analyze_query
    record={'_id':'control','product_id':'a','document_id':'a-label','section_title':'1 INDICATIONS AND USAGE',
            'source_text':'ALPHA treats plaque psoriasis in patients with migraine.'}
    assert not treatment_scores([record],analyze_query('What treats migraine?',None),{'a':Product('a','ALPHA','',[])})


def test_search_returns_the_complete_parent_heading_group_and_never_truncates_it(config, condition_library):
    run, _, corpus, _ = condition_library
    result=search_local('What treats diabetic macular edema?',run,config,corpus)
    assert [h['id'] for h in result.hits]==['parent','heading']
    assert not search_local('What treats diabetic macular edema?',run,config,corpus,limit=1).hits


def test_combination_indication_retains_co_therapy_and_prior_response_qualifiers():
    from amgen_explorer.condition_evidence import treatment_scores
    from amgen_explorer.query_intent import analyze_query
    text=('RIABNI, in combination with methotrexate, is indicated for the treatment of adult patients with '
          'moderately- to-severely-active rheumatoid arthritis who have had an inadequate response to one or more TNF antagonist therapies.')
    record={'_id':'ra','product_id':'ra','document_id':'ra-label','section_title':'1.3 Rheumatoid Arthritis (RA)', 'source_text':text}
    assert treatment_scores([record],analyze_query('Which medicines are indicated for rheumatoid arthritis?',None),
                            {'ra':Product('ra','RIABNI','',[])}) == {'ra':6}
    assert record['source_text']==text


def test_secondary_side_effect_phrase_cannot_bypass_treatment_gate(config, condition_library):
    run, _, corpus, _=condition_library
    result=search_local('What can treat migraine with fewer side effects?',run,config,corpus)
    assert result.match_mode=='treatment_evidence'
    assert not result.hits  # No source establishes the requested comparison.
    side_effects=search_local('What are the side effects of migraine treatment?',run,config,corpus)
    assert side_effects.match_mode=='content'
    assert any(h['id']=='adverse' for h in side_effects.hits)


@pytest.fixture(scope='module')
def supplied_use_blocks():
    from amgen_explorer.xml_store import load_corpus
    corpus=load_corpus(Path(__file__).resolve().parents[1]/'XML/AmgenProducts.xml')
    return corpus,{b.id:b for b in corpus.blocks}


@pytest.mark.parametrize('product,section,query,eligible',[
    ('xgeva','1-1','What treats multiple myeloma?',False),
    ('xgeva','1-1','What prevents multiple myeloma?',False),
    ('xgeva','1-1','What treats bone metastases?',False),
    ('xgeva','1-1','What prevents skeletal-related events?',True),
    ('prolia','1-4','What treats prostate cancer?',False),
    ('prolia','1-5','What treats breast cancer?',False),
    ('neulasta','1-1','What treats cancer?',False),
    ('neupogen','1-1','What treats cancer?',False),
    ('prolia','1-2','What treats osteoporosis in men?',True),
    ('enbrel','1-1','What treats rheumatoid arthritis?',True),
])
def test_supplied_labels_distinguish_therapeutic_goal_from_population(supplied_use_blocks,product,section,query,eligible):
    from amgen_explorer.condition_evidence import treatment_scores
    from amgen_explorer.query_intent import analyze_query
    corpus,blocks=supplied_use_blocks
    matching=[b for b in blocks.values() if b.product_id=='product-'+product and b.section_id.endswith('-section-'+section)]
    assert matching, 'The exact supplied source section must be present.'
    records=[{'_id':b.id,'product_id':b.product_id,'document_id':b.document_id,'document_sha256':b.document_sha256,
              'xml_hash':corpus.xml_hash,'section_id':b.section_id,'section_title':b.section_title,'source_text':b.text} for b in matching]
    assert bool(treatment_scores(records,analyze_query(query,corpus),{p.id:p for p in corpus.products})) is eligible


@pytest.mark.parametrize('text,query,eligible',[
 ('ALPHA is indicated for the treatment of migraine and BETA is used to treat psoriasis.','What treats psoriasis?',False),
 ('ALPHA is used for the treatment of asthma in adults who previously received treatment for migraine.','What treats migraine?',False),
 ('ALPHA is used not to treat migraine but to prevent asthma.','What treats migraine?',False),
 ('ALPHA is indicated for acute treatment of asthma and prevention of migraine.','What prevents asthma?',False),
 ('ALPHA is indicated for preventive treatment of migraine and acute treatment of asthma.','What treats acute migraine?',False),
 ('ALPHA is used for conditions except migraine.','What treats migraine?',False),
 ('ALPHA is used for asthma rather than migraine.','What treats migraine?',False),
 ('ALPHA is indicated for the treatment of breast cancer in adults.','What treats breast cancer?',True),
])
def test_attribution_history_and_predicate_qualifiers(text,query,eligible):
    from amgen_explorer.condition_evidence import treatment_scores
    from amgen_explorer.query_intent import analyze_query
    record={'_id':'control','product_id':'a','document_id':'a-label','section_title':'1 INDICATIONS AND USAGE','source_text':text}
    assert bool(treatment_scores([record],analyze_query(query,None),{'a':Product('a','ALPHA','',[])})) is eligible


def test_general_approved_use_prompt_keeps_section_context_not_a_fake_condition():
    from amgen_explorer.query_intent import analyze_query
    assert analyze_query('What approved uses does the source describe?',None).treatment_intent is None
    assert analyze_query('What approved uses and limitations does this source describe?',None).treatment_intent is None
    assert analyze_query('What are approved uses for migraine?',None).treatment_intent == 'treatment'
