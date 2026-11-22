"""Controlled retrieval comparisons with source-pinned expected evidence.

Scores measure retrieval on a fixed fixture suite, never clinical accuracy.
"""
from __future__ import annotations
from .errors import UserFacingError
import json
import re
import statistics
import time
from pathlib import Path
from .review import digest
from .source_import import inspect_inventory
from .library import BULK_POLICY
from .search import RANKING_VERSION, ARTIFACT_VERSION
from .service import atomic_json


def _spans(hit):
    spans=hit.get('metadata',{}).get('source_spans',[])
    return json.loads(spans) if isinstance(spans,str) else spans


def _union(intervals):
    result=[]
    for start,end in sorted(intervals):
        if result and start<=result[-1][1]:result[-1][1]=max(end,result[-1][1])
        else:result.append([start,end])
    return result


def score_case(case,hits,*,evidence_budget):
    kept=[];used=0
    for hit in hits:
        cost=hit.get('metadata',{}).get('indexed_text_bytes',len(hit['text'].encode('utf-8')))+8
        if used+cost>evidence_budget:continue
        used+=cost;kept.append(hit)
    expected=set(case.get('expected_document_ids',[]))
    docs=[h['metadata']['document_id'] for h in kept]
    recall=len(set(docs)&expected)/len(expected) if expected else 0
    rank=next((1/(i+1) for i,d in enumerate(docs) if d in expected),0)
    total=covered=0
    for span in case.get('expected_spans',[]):
        total+=span['end']-span['start'];intersections=[]
        for hit in kept:
            meta=hit['metadata']
            if meta['document_id']!=span['document_id'] or meta.get('document_sha256')!=span['document_sha256']:continue
            for candidate in _spans(hit):
                if candidate['page']==span['page']:
                    lo=max(candidate['start'],span['start']);hi=min(candidate['end'],span['end'])
                    if lo<hi:intersections.append((lo,hi))
        covered+=sum(hi-lo for lo,hi in _union(intersections))
    contaminated=sum(bool((case.get('document_id') and h['metadata']['document_id']!=case['document_id']) or
                           (case.get('product_id') and h['metadata']['product_id']!=case['product_id'])) for h in kept)
    return {'document_recall_at_k':recall,'reciprocal_rank':rank,'quote_coverage':covered/total if total else 0,
            'contamination_rate':contaminated/len(kept) if kept else 0,
            'evidence_bytes_with_reserve':used,'expected_characters':total,'covered_expected_characters':covered,'hits':kept}


def _grade(case, hit):
    meta=hit.get('metadata',{})
    did=meta.get('document_id',hit.get('document_id'))
    matches=[]
    for judgment in case.get('relevance_judgments',[]):
        if judgment.get('document_id')!=did:continue
        if judgment.get('document_sha256')!=meta.get('document_sha256'):continue
        for span in _spans(hit):
            if (span.get('page')==judgment.get('page') and
                    max(span.get('start',0),judgment['start'])<min(span.get('end',0),judgment['end'])):
                matches.append(judgment['grade'])
    if matches:return max(matches)
    for judgment in case.get('document_judgments',[]):
        if judgment['document_id']==did:return judgment['grade']
    # A default is an explicit judgment, never inferred from missing labels.
    return case.get('other_documents_grade')


def score_discovery(case: dict, hits: list[dict], *, k: int) -> dict:
    """Score visible discovery before teaching clipping; unknown is not zero.

    Precision uses the number of displayed hits (up to the cutoff). If any hit
    lacks a judgment the complete precision is unavailable; judged precision
    and judgment coverage remain visible. Graded relevance is mean grade / 3.
    """
    if type(k) is not int or k<1:raise ValueError('Discovery cutoff must be positive.')
    def at(cutoff):
        grades=[_grade(case,h) for h in hits[:cutoff]]
        judged=[g for g in grades if g is not None]
        precision=sum(g>0 for g in judged)/len(judged) if judged else 0
        return (precision if len(judged)==len(grades) else None),precision
    grades=[_grade(case,h) for h in hits[:k]];judged=[g for g in grades if g is not None]
    p5,j5=at(5);p10,j10=at(10)
    mean=sum(judged)/len(judged) if judged else 0
    return {'precision_at_5':p5,'precision_at_10':p10,
            'judged_precision_at_5':j5,'judged_precision_at_10':j10,
            'graded_relevance':mean/3 if len(judged)==len(grades) else None,
            'mean_relevance_grade':mean,'judgment_coverage':len(judged)/len(grades) if grades else 1,
            'judged_hits':len(judged),'unjudged_hits':len(grades)-len(judged),'visible_hits':len(grades)}


def score_behavior(case, result):
    """Execute retrieval assertions; generation-only fixtures remain unmeasured."""
    get=lambda key,default=None:result.get(key,default) if isinstance(result,dict) else getattr(result,key,default)
    expected=case.get('expected_outcome')
    if expected is None:
        return {'behavior_correct':None,'no_answer_correct':None,'suggestion_correct':None,
                'status':'not_measured','reason':'Generation/source-context assertion requires a dedicated answer evaluation.'}
    actual=get('outcome','results' if get('hits',[]) else 'no_results')
    outcome_correct=actual==expected
    suggestions={s.casefold() for s in get('suggestions',[])}
    expected_suggestions={s.casefold() for s in case.get('expected_suggestions',[])}
    suggestion_correct=expected_suggestions<=suggestions if expected_suggestions else None
    no_answer_correct=(not get('hits',[])) if expected=='no_results' else None
    return {'behavior_correct':outcome_correct and suggestion_correct is not False and no_answer_correct is not False,
            'outcome_correct':outcome_correct,'no_answer_correct':no_answer_correct,
            'suggestion_correct':suggestion_correct,'expected_outcome':expected,'actual_outcome':actual,'status':'measured'}


def _suite(service,suite_id,corpus):
    """Materialize a deterministic suite for this source version without dropping expectations."""
    import hashlib
    if not isinstance(suite_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',suite_id):
        raise UserFacingError('Invalid evaluation suite name.')
    path=service.config.root/'evals'/(suite_id+'.jsonl')
    try:
        payload=path.read_bytes();rows=[json.loads(line) for line in payload.decode().splitlines() if line.strip()]
    except (OSError,ValueError,UnicodeError):raise UserFacingError('The evaluation suite is missing or invalid.') from None
    if not rows or len(rows)>100 or len({r['id'] for r in rows})!=len(rows):
        raise UserFacingError('The evaluation suite must contain 1–100 unique questions.')
    archives={(b.document_id,b.page_start):b for b in corpus.blocks if b.section_kind=='sourcePageArchive'}
    documents={d.id:d for d in corpus.documents};products={p.id:p for p in corpus.products}
    measured=[];behavior=[]
    for row in rows:
        if not re.fullmatch(r'[a-f0-9]{64}',row.get('xml_hash','')):
            raise UserFacingError('The evaluation suite has an invalid XML source version.')
        source_changed=row['xml_hash']!=corpus.xml_hash
        row['suite_source_xml_hash']=row['xml_hash'];row['xml_hash']=corpus.xml_hash
        for judgment in row.get('relevance_judgments',[]):
            document=documents.get(judgment.get('document_id'))
            if document is None or document.sha256!=judgment.get('document_sha256'):
                raise UserFacingError('Discovery judgments refer to changed source PDFs. Create a separately versioned, relabeled suite before comparison.')
        if row.get('expected_outcome') or (row.get('expected_behavior') and not row.get('expected_document_ids')):
            behavior.append(row);continue
        if not row.get('question') or not row.get('expected_document_ids') or not row.get('expected_spans'):
            raise UserFacingError('The evaluation suite needs questions, expected documents and exact source spans.')
        unavailable=[];bound=[]
        for span in row['expected_spans']:
            span=dict(span);doc=documents.get(span.get('document_id'))
            if (not re.fullmatch(r'[a-f0-9]{64}',span.get('document_sha256',''))
                    or type(span.get('start')) is not int or type(span.get('end')) is not int
                    or not 0<=span['start']<span['end']):
                raise UserFacingError('The evaluation suite has an invalid expected source span.')
            block=archives.get((span['document_id'],span['page']))
            exact=(block and block.document_sha256==span['document_sha256'] and span['end']<=len(block.text)
                   and ('quote' not in span or block.text[span['start']:span['end']]==span['quote']))
            if exact:
                bound.append(span);continue
            # Source updates may move an unchanged literal quotation. Rebind only
            # when it resolves uniquely; retain unavailable expectations as zero
            # coverage in both versions rather than improving scores by exclusion.
            if not source_changed or (doc and doc.sha256==span['document_sha256']):
                raise UserFacingError('The evaluation suite has an unresolved expected source span.')
            matches=[];quote=span.get('quote')
            if quote and doc:
                for (did,page),candidate in archives.items():
                    if did!=doc.id:continue
                    start=0
                    while (offset:=candidate.text.find(quote,start))>=0:
                        matches.append({'document_id':did,'document_sha256':doc.sha256,'page':page,
                                        'start':offset,'end':offset+len(quote),'quote':quote})
                        start=offset+1
            if len(matches)==1:bound.append(matches[0])
            else:
                bound.append(span);unavailable.append(span['document_id'])
        row['expected_spans']=bound
        row['unavailable_expected_sources']=sorted(set(unavailable))
        measured.append(row)
    if not measured:raise UserFacingError('The evaluation suite contains no measurable retrieval cases.')
    covered={did for row in measured for did in row['expected_document_ids']}
    for doc in corpus.documents:
        if doc.id in covered:continue
        candidates=[b for b in corpus.blocks if b.document_id==doc.id and b.text.strip()]
        block=next((b for b in candidates if 'mechanism' in b.section_title.lower()),candidates[0] if candidates else None)
        if not block:continue
        source=block.spans[0];archive=archives[(doc.id,source['page'])]
        lo=source['start'];hi=min(source['end'],lo+180)
        measured.append({'id':'generated-'+doc.id,'kind':'source_lookup','question':products[doc.product_id].name+(' '+block.section_title if 'mechanism' in block.section_title.lower() else ''),
            'product_id':doc.product_id,'document_id':doc.id,'expected_document_ids':[doc.id],'xml_hash':corpus.xml_hash,
            'expected_spans':[{'document_id':doc.id,'document_sha256':doc.sha256,'page':source['page'],'start':lo,'end':hi,'quote':archive.text[lo:hi]}],
            'fixture_origin':'Automatically source-bound coverage case, not a clinical evaluation'})
    identity={'template_sha256':hashlib.sha256(payload).hexdigest(),'xml_hash':corpus.xml_hash,
              'binding_version':'exact-quote-v1','retrieval_cases':measured,'behavioral_cases':behavior}
    suite_hash=digest(identity)
    atomic_json(service.config.root/'data/evaluation-suites'/(suite_hash+'.json'),identity)
    return measured,behavior,suite_hash


def _compatible(service,a,b,suite_hash):
    for run in (a,b):
        if not run or not run.get('full_library') or run.get('eligibility_policy')!=BULK_POLICY:
            raise UserFacingError('Both configurations require verified full-library builds.')
    for key in ('xml_hash','source_registry_fingerprint','eligibility_policy','eligibility_fingerprint','profile','document_ids','product_ids'):
        if a.get(key)!=b.get(key):raise UserFacingError('Update the full library first: sources, policy and embedding profile must match for comparison.')
    for run in (a,b):
        if run.get('search_artifact',{}).get('ranking_version')!=ARTIFACT_VERSION:
            raise UserFacingError('Both configurations require compatible pinned search artifacts.')
    controls={'xml_hash':a['xml_hash'],'source_registry':a['source_registry_fingerprint'],
              'eligibility':a['eligibility_fingerprint'],'profile':a['profile'],
              'suite_hash':suite_hash,'ranking_version':RANKING_VERSION,
              'search':{'result_limit':service.config.settings.get('search',{}).get('result_limit',20),
                        'semantic_candidates':service.config.settings.get('search',{}).get('semantic_candidates',60)},
              'retrieval':service.config.settings['retrieval'],'generation':service.config.settings['openai']}
    return digest(controls),controls


def _citation_rate(service,run,hits):
    corpus=service._pinned_corpus(run['xml_hash'])
    archives={(b.document_id,b.page_start):b for b in corpus.blocks if b.section_kind=='sourcePageArchive'}
    resolved=0
    for hit in hits:
        meta=hit['metadata'];parts=[];valid=True
        for span in _spans(hit):
            block=archives.get((meta['document_id'],span['page']))
            if (not block or block.document_sha256!=meta.get('document_sha256') or
                    not 0<=span['start']<span['end']<=len(block.text)):
                valid=False;break
            parts.append(block.text[span['start']:span['end']])
        # Chunks can insert a newline between contiguous original blocks.
        if valid and parts and (''.join(parts)==hit['text'] or '\n'.join(parts)==hit['text']):resolved+=1
    return resolved/len(hits) if hits else 0


def evaluate_versions(service,baseline_run_id,candidate_run_id,suite_id='global-search',*,generate_answers=False):
    if baseline_run_id==candidate_run_id:raise UserFacingError('Choose different chunk configurations to compare.')
    a=service.library_version(baseline_run_id);b=service.library_version(candidate_run_id)
    corpus=service._pinned_corpus(a['xml_hash'])
    cases,behavior,suite_hash=_suite(service,suite_id,corpus)
    fingerprint,controls=_compatible(service,a,b,suite_hash)
    rows=[];warnings=[f"Unavailable expected source evidence retained with zero quote coverage: {case['id']} ({', '.join(case['unavailable_expected_sources'])})" for case in cases if case.get('unavailable_expected_sources')];usage={'baseline':{},'candidate':{}};modes={'baseline':set(),'candidate':set()};observations=[]
    visible_limit=service.config.settings.get('search',{}).get('result_limit',20)
    for number,case in enumerate(cases):
        row={'id':case['id'],'question':case['question'],'expected_document_ids':case['expected_document_ids']}
        # Alternate order to reduce systematic first-request latency bias.
        sequence=[('baseline',a),('candidate',b)]
        if number%2:sequence.reverse()
        for label,run in sequence:
            started=time.monotonic()
            result=service.search_library(case['question'],run_id=run['run_id'],
                product_ids=case.get('requested_filters',{}).get('product_ids'),
                document_ids=case.get('requested_filters',{}).get('document_ids'),
                limit=visible_limit)
            score=score_case(case,result.hits[:service.config.settings['retrieval']['top_k']],evidence_budget=service.config.settings['retrieval']['evidence_token_budget'])
            score.update(score_discovery(case,result.hits,k=visible_limit))
            score.update(latency_ms=round((time.monotonic()-started)*1000,3),degraded=result.degraded,
                         citation_resolution=_citation_rate(service,run,score['hits']))
            row[label]=score;modes[label].add(result.degraded)
            warnings.extend(result.warnings)
            for key,value in result.usage.items():
                if isinstance(value,(int,float)):usage[label][key]=usage[label].get(key,0)+value
            if generate_answers and case.get('product_id') and case.get('document_id'):
                answer=service.answer(case['question'],case['product_id'],document_id=case['document_id'],run_id=run['run_id'])
                observations.append({'case_id':case['id'],'version':label,'abstained':answer.abstained,
                                     'citation_count':len(answer.citations),'usage':answer.usage})
        rows.append(row)
    behavioral_results=[]
    for case in behavior:
        row={'id':case['id'],'question':case['question']}
        for label,run in (('baseline',a),('candidate',b)):
            if not case.get('expected_outcome'):
                row[label]=score_behavior(case,{})
                continue
            result=service.search_library(case['question'],run_id=run['run_id'],
                product_ids=case.get('requested_filters',{}).get('product_ids'),
                document_ids=case.get('requested_filters',{}).get('document_ids'),
                limit=visible_limit)
            row[label]=score_behavior(case,result)
            row[label]['discovery']=score_discovery(case,result.hits,k=visible_limit)
            warnings.extend(result.warnings);modes[label].add(result.degraded)
            for key,value in result.usage.items():
                if isinstance(value,(int,float)):usage[label][key]=usage[label].get(key,0)+value
        behavioral_results.append(row)
    metrics={}
    for label in ('baseline','candidate'):
        metrics[label]={name:round(statistics.mean(r[label][key] for r in rows),6) for name,key in
            [('document_recall_at_k','document_recall_at_k'),('mean_reciprocal_rank','reciprocal_rank'),
             ('quote_coverage','quote_coverage'),('citation_resolution','citation_resolution'),
             ('contamination_rate','contamination_rate'),('mean_latency_ms','latency_ms')]}
        metrics[label]['question_count']=len(rows)
        for name in ('precision_at_5','precision_at_10','graded_relevance','judgment_coverage'):
            observed=[r[label][name] for r in rows if r[label][name] is not None]
            metrics[label][name]=round(statistics.mean(observed),6) if observed else None
            metrics[label][name+'_measured_cases']=len(observed)
        for name in ('behavior_correct','no_answer_correct','suggestion_correct'):
            observed=[r[label][name] for r in behavioral_results if r[label][name] is not None]
            metrics[label][name]=round(statistics.mean(observed),6) if observed else None
            metrics[label][name+'_measured_cases']=len(observed)
    compatible=modes['baseline']==modes['candidate'] and len(modes['baseline'])==1
    if not compatible:warnings.append('Search availability differed during this comparison. Rerun before choosing a configuration.')
    report={'baseline_run_id':a['run_id'],'candidate_run_id':b['run_id'],'candidate':b,'suite_id':suite_id,
            'suite_hash':suite_hash,'compatibility_fingerprint':fingerprint,'controls':controls,'compatible':compatible,
            'metrics':metrics,'rows':rows,'warnings':list(dict.fromkeys(warnings)),'usage':usage,
            'behavioral_cases_retained':len(behavior),'behavioral_results':behavioral_results,'generated_answer_observations':observations,
            'searchable_coverage':{'baseline':a['coverage'],'candidate':b['coverage']},
            'latency_conditions':'Sequential calls with alternating baseline/candidate order; includes local integrity checks. Provider caches are uncontrolled.',
            'note':'Expected-document and exact-span retrieval measurements under the same evidence budget. Visible discovery quality is independent of teaching budget; retrieval behaviors are executed, generation-only assertions are explicitly unmeasured. These are not clinical accuracy scores.',
            'created_at':time.time()}
    path=service.config.root/'data/experiments'/(digest({'a':a['run_id'],'b':b['run_id'],'controls':fingerprint})+'.json')
    atomic_json(path,report)
    return report


def test_chunk_configuration(service,chunk_config,suite_id='global-search',*,on_progress=None):
    baseline=service.library_version()
    if not baseline or not baseline.get('full_library'):raise UserFacingError('Build the full library before testing chunk settings.')
    if chunk_config.fingerprint()==baseline['config_hash']:raise UserFacingError('Choose different chunk settings before testing.')
    registry=inspect_inventory(service.config,service.corpus())
    if registry['fingerprint']!=baseline.get('source_registry_fingerprint'):
        raise UserFacingError('Update the full library before testing: source documents changed.')
    _suite(service,suite_id,service._pinned_corpus(baseline['xml_hash']))
    candidate=service.build_library(chunk_config,activate=False,on_progress=on_progress)
    if on_progress:on_progress({'stage':'Comparing saved questions','status':'evaluating'})
    report=evaluate_versions(service,baseline['run_id'],candidate['run_id'],suite_id)
    active=service.active()
    if not active or active['run_id']!=baseline['run_id']:
        report['compatible']=False;report['warnings'].append('The active baseline changed while testing. Rerun before choosing this configuration.')
    return report
