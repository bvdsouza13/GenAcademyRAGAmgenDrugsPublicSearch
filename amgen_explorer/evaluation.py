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
from .search import RANKING_VERSION
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
        cost=len(hit['text'].encode('utf-8'))+8
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
        if row.get('expected_behavior') and not row.get('expected_document_ids'):
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
        measured.append({'id':'generated-'+doc.id,'kind':'source_lookup','question':products[doc.product_id].name+' '+block.section_title,
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
        if run.get('search_artifact',{}).get('ranking_version')!=RANKING_VERSION:
            raise UserFacingError('Rebuild both configurations with the same search ranking version.')
    controls={'xml_hash':a['xml_hash'],'source_registry':a['source_registry_fingerprint'],
              'eligibility':a['eligibility_fingerprint'],'profile':a['profile'],
              'suite_hash':suite_hash,'ranking_version':RANKING_VERSION,
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
    for number,case in enumerate(cases):
        row={'id':case['id'],'question':case['question'],'expected_document_ids':case['expected_document_ids']}
        # Alternate order to reduce systematic first-request latency bias.
        sequence=[('baseline',a),('candidate',b)]
        if number%2:sequence.reverse()
        for label,run in sequence:
            started=time.monotonic()
            result=service.search_library(case['question'],run_id=run['run_id'],
                product_ids=[case['product_id']] if case.get('product_id') else None,
                document_ids=[case['document_id']] if case.get('document_id') else None,
                limit=service.config.settings['retrieval']['top_k'])
            score=score_case(case,result.hits,evidence_budget=service.config.settings['retrieval']['evidence_token_budget'])
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
    metrics={}
    for label in ('baseline','candidate'):
        metrics[label]={name:round(statistics.mean(r[label][key] for r in rows),6) for name,key in
            [('document_recall_at_k','document_recall_at_k'),('mean_reciprocal_rank','reciprocal_rank'),
             ('quote_coverage','quote_coverage'),('citation_resolution','citation_resolution'),
             ('contamination_rate','contamination_rate'),('mean_latency_ms','latency_ms')]}
        metrics[label]['question_count']=len(rows)
    compatible=modes['baseline']==modes['candidate'] and len(modes['baseline'])==1
    if not compatible:warnings.append('Search availability differed during this comparison. Rerun before choosing a configuration.')
    report={'baseline_run_id':a['run_id'],'candidate_run_id':b['run_id'],'candidate':b,'suite_id':suite_id,
            'suite_hash':suite_hash,'compatibility_fingerprint':fingerprint,'controls':controls,'compatible':compatible,
            'metrics':metrics,'rows':rows,'warnings':list(dict.fromkeys(warnings)),'usage':usage,
            'behavioral_cases_retained':len(behavior),'generated_answer_observations':observations,
            'searchable_coverage':{'baseline':a['coverage'],'candidate':b['coverage']},
            'latency_conditions':'Sequential calls with alternating baseline/candidate order; includes local integrity checks. Provider caches are uncontrolled.',
            'note':'Expected-document and exact-span retrieval measurements under the same evidence budget. Behavioral fixtures remain separate regression cases. These are not clinical accuracy scores.',
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
