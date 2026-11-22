#!/usr/bin/env python3
"""Explicit live checks of full-library search and optional cited teaching (API usage)."""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amgen_explorer.service import ExplorerService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chat',action='store_true',help='Also call OpenAI for three source-scoped teaching questions')
    parser.add_argument('--output',default='output/bulk-live-check.json')
    args=parser.parse_args()
    service=ExplorerService();run=service.library_version()
    if not run or not run.get('full_library'):raise ValueError('Build a full searchable library first.')
    report={'run_id':run['run_id'],'record_count':run['record_count'],'document_count':len(run['document_ids']),
            'product_count':len(run['product_ids']),'coverage':run['coverage'],'searches':[],'teaching':[]}
    for query in ['ACTIMMUNE','latex','storage temperature','interferons bind']:
        result=service.search_library(query,run_id=run['run_id'])
        if not result.hits:raise ValueError('Search returned no results for a smoke-test query.')
        if result.degraded:raise ValueError('Semantic search is degraded during the live smoke check.')
        if query=='ACTIMMUNE' and not any(h['metadata']['product_id']=='product-actimmune' for h in result.hits):
            raise ValueError('ACTIMMUNE did not appear in its search results.')
        if query=='latex':
            variants={h['metadata']['document_id'] for h in result.hits if h['metadata']['product_id']=='product-repatha'}
            if len(variants)!=2:raise ValueError('Both Repatha source variants must remain discoverable.')
        for did in {h['metadata']['document_id'] for h in result.hits}:
            service.source_pdf(did,run['xml_hash'])
        report['searches'].append({'query':query,'hits':len(result.hits),'documents':sorted({h['metadata']['document_id'] for h in result.hits}),
                                   'latency_ms':result.latency_ms,'usage':result.usage,'degraded':result.degraded})
    failures=[]
    if args.chat:
        for product,document,question in [
            ('product-actimmune','doc-actimmune-prescribing-information','What mechanism of action does the source describe?'),
            ('product-repatha','doc-repatha-prescribing-information-dry-natural-rubber','What does this source say about latex?'),
            ('product-tezspire','doc-tezspire-prescribing-information','What mechanism of action does the source describe?')]:
            # Resolve the actual filename-derived variant identity from the pinned library.
            if document not in run['document_ids']:
                options=[d.id for d in service.library_corpus(run['run_id']).documents if d.product_id==product]
                document=next((d for d in options if 'dry' in d),options[0])
            started=time.monotonic();response=service.answer(question,product,document_id=document,run_id=run['run_id'])
            if not response.citations:raise ValueError('Teaching returned no cited source for a supported test question.')
            report['teaching'].append({'product_id':product,'document_id':document,'question':question,
               'answer':response.answer,'abstained':response.abstained,'citation_count':len(response.citations),
               'usage':response.usage,'seconds':round(time.monotonic()-started,3)})
            # These pinned scopes exercise distinct release contracts: ACTIMMUNE
            # must generate a verified answer; Tezspire must preserve its
            # restricted-layout source fallback. Repatha may do either.
            if response.usage.get('provider_problem'):
                failures.append(product+': explanation provider unavailable')
            elif product=='product-actimmune' and (response.abstained or response.usage.get('source_fallback')
                    or response.usage.get('explanation_verified') is not True):
                failures.append(product+': required verified generation did not succeed')
            elif product=='product-tezspire' and (not response.abstained
                    or response.usage.get('source_fallback') is not True
                    or response.usage.get('explanation_verified') is not False):
                failures.append(product+': required restricted-source fallback did not succeed')
    report['status']='failed' if failures else 'passed'
    report['failures']=failures
    path=ROOT/args.output;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':report['status'],'output':str(path),'searches':len(report['searches']),'teaching':len(report['teaching']),'failures':failures}))
    return 1 if failures else 0

if __name__=='__main__':raise SystemExit(main())
