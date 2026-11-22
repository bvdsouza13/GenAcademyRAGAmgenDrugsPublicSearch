#!/usr/bin/env python3
"""Explicit full-library preparation, builds, content search and chunk experiments.

Legacy preview/load/publish/rollback commands remain for pilot recovery only.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amgen_explorer.service import ExplorerService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preview-library','build-library','test-settings','use-configuration','revert-library','search','status','verify-library','repair-library','readiness','recover-xml','recoverable-versions','restore-library','preview','load','publish','runs','rollback'])
    parser.add_argument('--target',type=int,default=600)
    parser.add_argument('--overlap',type=int,default=80)
    parser.add_argument('--product-id')
    parser.add_argument('--document-id')
    parser.add_argument('--run-id')
    parser.add_argument('--query')
    parser.add_argument('--suite',default='learner-search')
    parser.add_argument('--candidate-only',action='store_true')
    args=parser.parse_args()
    try:
        service=ExplorerService();config=service.chunk_config(args.target,args.overlap)
        if args.action=='preview-library':
            plan=service.preview_library(config);result={**service.index.preview(plan),'coverage':plan.coverage}
        elif args.action=='build-library':
            result=service.build_library(config,activate=not args.candidate_only,
                on_progress=lambda p:print(json.dumps({'stage':p.get('stage'),'processed':p.get('succeeded'),'records':p.get('record_count')}),file=sys.stderr))
        elif args.action=='test-settings':result=service.test_chunk_configuration(config,args.suite)
        elif args.action=='use-configuration':
            if not args.run_id:parser.error('--run-id is required')
            result=service.use_configuration(args.run_id)
        elif args.action=='revert-library':result=service.revert_library()
        elif args.action=='search':
            if not args.query:parser.error('--query is required')
            result=asdict(service.search_library(args.query,run_id=args.run_id,
                product_ids=[args.product_id] if args.product_id else None,document_ids=[args.document_id] if args.document_id else None))
        elif args.action=='status':result=service.library_status()
        elif args.action in {'verify-library','repair-library'}:
            result=service.verify_library(run_id=args.run_id,repair=args.action=='repair-library')
        elif args.action=='readiness':result=service.check_readiness(require_generation=True)
        elif args.action=='recover-xml':
            result=service.recover_working_xml()
            if not isinstance(result,dict):result=asdict(result)
        elif args.action=='recoverable-versions':result=service.list_recoverable_versions()
        elif args.action=='restore-library':
            if not args.run_id:parser.error('--run-id is required')
            result=service.restore_library_version(args.run_id)
        elif args.action=='runs':result=service.index.runs()
        elif args.action=='rollback':
            if not args.run_id:parser.error('--run-id is required for rollback')
            result=service.rollback(args.run_id)
        else:
            plan=service.preview(config,args.product_id,args.document_id)
            if args.action=='preview':result=service.index.preview(plan)
            elif args.action=='load':result=service.load(plan)
            else:
                if not args.run_id:parser.error('--run-id is required for publish')
                result=service.publish(args.run_id,plan)
        print(json.dumps(result,indent=2,ensure_ascii=False))
        if args.action in {'verify-library','repair-library'}:
            return 0 if result.get('outcome')=='verified' or result.get('ok') is True else 1
        if args.action=='readiness':return 0 if result.get('ok') else 1
        return 0
    except Exception as error:
        print(f'Operation did not complete ({type(error).__name__}). Check source inventory, configuration and connection status; the active library was not automatically replaced.',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
