"""Discovery quality is measured before teaching budget clipping and without hidden scope."""
import json
from pathlib import Path
import pytest
from amgen_explorer import evaluation


def hit(doc,start=0,end=10):
    return {'text':'x'*10,'metadata':{'document_id':doc,'document_sha256':'hash','source_spans':[{'page':1,'start':start,'end':end}]}}


def test_discovery_detects_irrelevant_tail_and_grades_source_spans():
    case={'document_judgments':[{'document_id':'d','grade':1}],
          'relevance_judgments':[{'document_id':'d','document_sha256':'hash','page':1,'start':0,'end':10,'grade':3}],
          'other_documents_grade':0}
    score=getattr(evaluation,'score_discovery',None)
    assert callable(score), 'Discovery scoring must exist independently of the teaching budget'
    focused=score(case,[hit('d')],k=10)
    noisy=score(case,[hit('d')]+[hit('other') for _ in range(9)],k=10)
    assert focused['precision_at_10']>noisy['precision_at_10']
    assert focused['graded_relevance']>noisy['graded_relevance']
    assert focused['judgment_coverage']==noisy['judgment_coverage']==1
    assert focused['mean_relevance_grade']==3


def test_unjudged_hits_are_not_mislabeled_irrelevant():
    score=getattr(evaluation,'score_discovery',None)
    assert callable(score)
    result=score({'document_judgments':[{'document_id':'d','grade':2}]},[hit('d'),hit('unknown')],k=5)
    assert result['judged_hits']==1 and result['unjudged_hits']==1
    assert result['judgment_coverage']==.5
    assert result['precision_at_5'] is None
    assert result['judged_precision_at_5']==1


def test_behavior_assertions_detect_wrong_no_answer_and_suggestion():
    check=getattr(evaluation,'score_behavior',None)
    assert callable(check)
    case={'expected_outcome':'clarification','expected_suggestions':['ACTIMMUNE']}
    assert check(case,{'outcome':'results','suggestions':[],'hits':[hit('d')]})['behavior_correct'] is False
    good=check(case,{'outcome':'clarification','suggestions':['ACTIMMUNE'],'hits':[]})
    assert good['behavior_correct'] and good['suggestion_correct']


def test_learner_suite_has_all_unfiltered_source_questions_and_frozen_partitions():
    root=Path(__file__).resolve().parents[1]
    rows=[json.loads(s) for s in (root/'evals/learner-search.jsonl').read_text().splitlines()]
    old=[json.loads(s) for s in (root/'evals/global-search.jsonl').read_text().splitlines()]
    source=[r for r in rows if r['kind']=='source_lookup']
    assert len(source)==37 and 1<=len(rows)<=100
    assert {r['question'] for r in source}=={r['question'] for r in old if r['kind']=='source_lookup'}
    assert all(r['requested_filters']=={} and 'product_id' not in r and 'document_id' not in r for r in rows)
    assert {r['partition'] for r in rows}=={'development','holdout'}
    assert all(r.get('relevance_judgments') or r.get('expected_outcome') for r in rows)


def test_evaluation_uses_only_requested_filters_and_executes_behaviors(tmp_path):
    from types import SimpleNamespace
    from amgen_explorer.evaluation import _suite
    class Service:
        config=SimpleNamespace(root=tmp_path)
    corpus=SimpleNamespace(xml_hash='a'*64,blocks=[],documents=[],products=[])
    folder=tmp_path/'evals';folder.mkdir()
    row={'id':'behavior','question':'qzxvnmqzxvnm','xml_hash':'a'*64,'kind':'learner_behavior',
         'expected_document_ids':[],'expected_outcome':'no_results','requested_filters':{},'partition':'holdout'}
    # A source case is needed to make the suite measurable.
    source={'id':'source','question':'source','xml_hash':'a'*64,'expected_document_ids':['d'],
            'expected_spans':[{'document_id':'d','document_sha256':'b'*64,'page':1,'start':0,'end':2}],
            'requested_filters':{},'partition':'development'}
    archive=SimpleNamespace(document_id='d',page_start=1,section_kind='sourcePageArchive',document_sha256='b'*64,text='ok')
    corpus.blocks=[archive]
    (folder/'learner.jsonl').write_text(json.dumps(source)+'\n'+json.dumps(row)+'\n')
    measured,behavior,_=_suite(Service(),'learner',corpus)
    assert len(measured)==len(behavior)==1
    assert measured[0]['requested_filters']=={}


def test_version_evaluation_does_not_filter_by_expected_identity(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from amgen_explorer.search import SearchResults
    cases=[{'id':'source','question':'latex','product_id':'p','document_id':'d','expected_document_ids':['d'],
            'requested_filters':{},'expected_spans':[],'document_judgments':[{'document_id':'d','grade':2}],'other_documents_grade':0}]
    behavior=[{'id':'nonsense','question':'qzxvnmqzxvnm','expected_outcome':'no_results','requested_filters':{}}]
    monkeypatch.setattr(evaluation,'_suite',lambda *args:(cases,behavior,'suite'))
    monkeypatch.setattr(evaluation,'_compatible',lambda *args:('fingerprint',{}))
    monkeypatch.setattr(evaluation,'_citation_rate',lambda *args:1)
    calls=[]
    def search(query,**kwargs):
        calls.append(kwargs)
        return SearchResults(query,kwargs['run_id'],'ns','a'*64)
    run=lambda rid:{'run_id':rid,'xml_hash':'a'*64,'coverage':{}}
    service=SimpleNamespace(config=SimpleNamespace(root=tmp_path,settings={'retrieval':{'top_k':5,'evidence_token_budget':100}}),
                            library_version=run,_pinned_corpus=lambda _:None,search_library=search)
    report=evaluation.evaluate_versions(service,'a','b')
    assert all(c['product_ids'] is None and c['document_ids'] is None for c in calls)
    assert len(report['behavioral_results'])==1
    assert report['behavioral_results'][0]['baseline']['behavior_correct']
    assert 'precision_at_5' in report['metrics']['baseline']


def test_precision_cutoffs_are_independent_of_teaching_k():
    case={'document_judgments':[{'document_id':'d','grade':3}],'other_documents_grade':0}
    result=evaluation.score_discovery(case,[hit('d')]*5+[hit('other')]*5,k=5)
    assert result['precision_at_5']==1 and result['precision_at_10']==.5


def test_changed_pdf_rejects_stale_discovery_judgments(tmp_path):
    from types import SimpleNamespace
    service=SimpleNamespace(config=SimpleNamespace(root=tmp_path))
    corpus=SimpleNamespace(xml_hash='a'*64,blocks=[],documents=[SimpleNamespace(id='d',sha256='c'*64)],products=[])
    folder=tmp_path/'evals';folder.mkdir()
    row={'id':'stale','question':'q','xml_hash':'b'*64,'expected_outcome':'results',
         'relevance_judgments':[{'document_id':'d','document_sha256':'d'*64,'page':1,'start':0,'end':5,'quote':'quote','grade':3}]}
    (folder/'learner.jsonl').write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError,match='judgments.*changed source'):
        evaluation._suite(service,'learner',corpus)
