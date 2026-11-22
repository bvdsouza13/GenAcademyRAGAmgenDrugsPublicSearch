import pytest
from amgen_explorer.evaluation import score_case


def hit(doc,start,end,text,product='p'):
    return {'id':doc+str(start),'text':text,'metadata':{'document_id':doc,'product_id':product,'document_sha256':'h','source_spans':[{'page':1,'start':start,'end':end}]}}


def test_partial_span_is_partial_not_a_successful_block_touch():
    case={'expected_document_ids':['d'],'expected_spans':[{'document_id':'d','document_sha256':'h','page':1,'start':0,'end':10}]}
    score=score_case(case,[hit('d',0,5,'hello')],evidence_budget=100)
    assert score['document_recall_at_k']==1 and score['quote_coverage']==0.5


def test_excluded_expected_source_remains_in_denominator():
    case={'expected_document_ids':['missing'],'expected_spans':[{'document_id':'missing','document_sha256':'h','page':1,'start':0,'end':10}]}
    score=score_case(case,[hit('other',0,10,'something!')],evidence_budget=100)
    assert score['document_recall_at_k']==0 and score['quote_coverage']==0


def test_union_does_not_double_count_overlapping_chunks():
    case={'expected_document_ids':['d'],'expected_spans':[{'document_id':'d','document_sha256':'h','page':1,'start':0,'end':10}]}
    score=score_case(case,[hit('d',0,6,'123456'),hit('d',4,10,'567890')],evidence_budget=100)
    assert score['quote_coverage']==1


def test_equal_evidence_budget_excludes_whole_hit_without_truncation():
    case={'expected_document_ids':['d'],'expected_spans':[{'document_id':'d','document_sha256':'h','page':1,'start':0,'end':10}]}
    score=score_case(case,[hit('d',0,10,'1234567890')],evidence_budget=10)
    assert score['quote_coverage']==0 and score['document_recall_at_k']==0


def test_contamination_requires_explicit_scope_global_other_docs_not_contamination():
    case={'expected_document_ids':['d']}
    assert score_case(case,[hit('other',0,2,'ab')],evidence_budget=100)['contamination_rate']==0
    case['document_id']='d'
    assert score_case(case,[hit('other',0,2,'ab')],evidence_budget=100)['contamination_rate']==1


def test_teaching_budget_counts_indexed_prefix_bytes():
    case={'expected_document_ids':['d']}
    record=hit('d',0,2,'ab')
    record['metadata']['indexed_text_bytes']=99
    score=score_case(case,[record],evidence_budget=100)
    assert score['hits']==[] and score['evidence_bytes_with_reserve']==0
