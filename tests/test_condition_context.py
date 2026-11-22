"""Chat context uses the same condition-use evidence as global discovery."""
from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path

import pytest

from amgen_explorer.connectivity import ProviderError
from amgen_explorer.indexing import manifest_records
from amgen_explorer.models import Corpus, Document, Product
from amgen_explorer.retrieval import retrieve
from amgen_explorer.search import build_search_artifact
from amgen_explorer.teaching import make_quiz, teach
from test_indexing import FakeDocuments, config, plan, service


@pytest.fixture(params=[True, False], ids=['fts5', 'token-engine'])
def context_library(config, plan, request):
    # Literal expectations deliberately separate an indication, its qualifier,
    # unrelated uses, incidental conditions and the other educational topics.
    sources = [
        ('use', '1.1', '1.1 Indications and usage: migraine', 'indications',
         'EXAMPLE is indicated for the preventive treatment of migraine in adults.'),
        ('qualifier', '1.1', '1.1 Indications and usage: migraine', 'indications',
         'Its safety and effectiveness in children have not been established.'),
        ('summary-use', 'highlights', 'Highlights and contents', 'highlights',
         'EXAMPLE is indicated for the preventive treatment of migraine in adults.'),
        ('other-use', '1.2', '1.2 Indications and usage: asthma', 'indications',
         'EXAMPLE is indicated for the treatment of asthma in adults.'),
        ('adverse', '6', '6 ADVERSE REACTIONS', 'adverse',
         'Migraine occurred in patients receiving EXAMPLE.'),
        ('concomitant', '14', '14 CLINICAL STUDIES', 'study',
         'Patients receiving EXAMPLE could use OTHERMED to treat migraine.'),
        ('caption', '14', '14 CLINICAL STUDIES', 'study', 'Intent-to-treat population.'),
        ('mechanism', '12.1', '12.1 Mechanism of action', 'mechanism',
         'EXAMPLE binds to the specified receptor.'),
        ('warning', '5', '5 WARNINGS AND PRECAUTIONS', 'warning',
         'Monitor for serious reactions during EXAMPLE treatment.'),
        ('dose', '2', '2 DOSAGE AND ADMINISTRATION', 'dosage',
         'The recommended EXAMPLE dose is stated in the supplied dosing schedule.'),
        ('storage', '16', '16 STORAGE', 'storage',
         'Store EXAMPLE refrigerated during the treatment period.'),
    ]
    prototype = plan.chunks[0]
    plan.chunks = []
    for i, (rid, section, title, kind, text) in enumerate(sources):
        chunk = deepcopy(prototype)
        chunk.id = rid
        chunk.text = text
        chunk.metadata.update(product_name='EXAMPLE', source_text=text,
            section_id=section, section_title=title, section_kind=kind,
            source_spans=json.dumps([{'page':1, 'start':i*1000,
                'end':i*1000+len(text), 'archive_block_id':'doc-page'}]))
        if rid == 'summary-use':
            chunk.metadata['extraction_limitations']=['unresolved_table']
        if rid in ('use', 'qualifier'):
            chunk.metadata.update(continuation_parent_ids=['indication-parent'],
                continuation_count=2, continuation_index=0 if rid=='use' else 1)
        plan.chunks.append(chunk)
    provider = FakeDocuments()
    run = service(config, provider).ingest(plan)
    records = manifest_records(run, config)
    corpus = Corpus(Path('synthetic.xml'), run['xml_hash'],
        [Product('medicine','EXAMPLE','example-antibody',['doc'])],
        [Document('doc','medicine','medicine.pdf','d'*64,1,'2025','')], [])
    run['search_artifact'] = asdict(build_search_artifact(run, records, corpus, config,
                                                         use_fts5=request.param))
    return run, records, corpus, provider


@pytest.mark.parametrize('question', ['What can treat migraine?', 'What are approved uses for migraine?',
                                     'What can prevent migraine?'])
@pytest.mark.parametrize('outage', [False, True])
def test_condition_chat_keeps_complete_use_context_without_unrelated_sections(config, context_library, question, outage):
    run, records, corpus, provider = context_library
    writes = deepcopy(provider.writes)
    if outage:
        def fail(*args): raise ProviderError('Pinecone',503)
        provider.search = fail
    else:
        provider.search = lambda *args: list(reversed(records))
    result = retrieve(question,'medicine',run,config,'doc',client=provider,corpus=corpus)
    assert {p['id'] for p in result.passages} == {'use','qualifier'}
    assert result.passages[0]['text'] == 'EXAMPLE is indicated for the preventive treatment of migraine in adults.'
    assert result.passages[1]['text'] == 'Its safety and effectiveness in children have not been established.'
    assert all(p['run_id']==run['run_id'] and p['xml_hash']==run['xml_hash'] for p in result.passages)
    assert provider.writes == writes
    assert any('degraded' in warning for warning in result.warnings) == outage


@pytest.mark.parametrize('question', ['What treats malaria?', 'What treats migraine in children?',
                                     'What treats acute migraine?'])
@pytest.mark.parametrize('outage', [False, True])
def test_unsupported_condition_context_cannot_feed_explanations_or_quizzes(config, context_library, question, outage):
    run, _, corpus, provider = context_library
    if outage:
        def fail(*args): raise ProviderError('Pinecone',503)
        provider.search = fail
    result = retrieve(question,'medicine',run,config,'doc',client=provider,corpus=corpus)
    assert not result.passages
    class NoAI:
        def generate(self,*args,**kwargs):
            raise AssertionError('Unsupported context reached generation')
    response = teach(question,result,config,client=NoAI())
    assert response.abstained and not response.citations
    assert 'error' in make_quiz(result,config)


@pytest.mark.parametrize('question,wanted,expected', [
    ('What warnings apply during migraine treatment?', 'warning', {'warning','adverse'}),
    ('Explain the mechanism during migraine treatment.', 'mechanism', {'mechanism'}),
    ('Explain the dosage during migraine treatment.', 'dose', {'dose'}),
    ('How should EXAMPLE be stored during migraine treatment?', 'storage', {'storage'}),
])
def test_other_context_topics_do_not_become_treatment_discovery(config, context_library, question, wanted, expected):
    run, records, corpus, provider = context_library
    provider.search = lambda *args: [next(r for r in records if r['_id']==wanted)]
    result = retrieve(question,'medicine',run,config,'doc',client=provider,corpus=corpus)
    assert {p['id'] for p in result.passages} == expected


def test_standard_mechanism_quiz_keeps_mechanism_source(config, context_library):
    run, records, corpus, provider = context_library
    provider.search = lambda *args: list(reversed(records))
    result = retrieve('How does this medicine work? Explain its mechanism of action.',
                      'medicine',run,config,'doc',client=provider,corpus=corpus)
    quiz = make_quiz(result,config)
    assert [p['id'] for p in result.passages] == ['mechanism']
    assert quiz['choices'][quiz['correct_index']] == 'EXAMPLE binds to the specified receptor.'
    assert quiz['run_id'] == run['run_id'] and quiz['document_id']=='doc'


def test_linked_parent_and_condition_heading_cannot_be_partially_packed():
    from amgen_explorer.evidence_selection import select_evidence
    from test_evidence_selection import record
    parent=record('parent','indications',body='EXAMPLE is indicated for the treatment of:')
    child=record('child','indications',body='Diabetic macular edema (DME).')
    result=select_evidence('What treats diabetic macular edema?', [parent,child], ['parent','child'],
        budget_bytes=65, intent='general', required_groups=[['parent','child']])
    assert not result.records and not result.complete
    assert set(result.omitted_ids)=={'parent','child'}
    assert any('required context' in reason.lower() for reason in result.reasons)
    complete=select_evidence('What treats diabetic macular edema?', [parent,child], ['parent','child'],
        budget_bytes=1000, intent='general', required_groups=[['parent','child']])
    assert [row['_id'] for row in complete.records]==['parent','child']


def test_missing_linked_parent_is_not_silently_ignored():
    from amgen_explorer.evidence_selection import select_evidence
    from test_evidence_selection import record
    child=record('child','indications',body='Diabetic macular edema (DME).')
    result=select_evidence('What treats diabetic macular edema?', [child], ['child'],
        budget_bytes=1000, intent='general', required_groups=[['parent','child']])
    assert not result.records and not result.complete


def test_linked_source_context_never_combines_documents():
    from amgen_explorer.evidence_selection import select_evidence
    from test_evidence_selection import record
    parent=record('parent','indications')
    child={**record('child','indications'),'document_id':'other'}
    with pytest.raises(ValueError,match='document identities'):
        select_evidence('What treats migraine?', [parent,child], ['parent','child'],
            budget_bytes=1000, intent='general', required_groups=[['parent','child']])
