#!/usr/bin/env python3
"""Explicit local preview, staged cloud load, publication and rollback."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amgen_explorer.service import ExplorerService

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preview", "load", "publish", "runs", "rollback"])
    parser.add_argument("--target", type=int, default=600)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument("--product-id")
    parser.add_argument("--document-id")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        service = ExplorerService()
        if args.action == "runs":
            result = service.index.runs()
        elif args.action == "rollback":
            if not args.run_id: parser.error("--run-id is required for rollback")
            result = service.rollback(args.run_id)
        else:
            plan = service.preview(service.chunk_config(args.target, args.overlap), args.product_id, args.document_id)
            if args.action == "preview": result = service.index.preview(plan)
            elif args.action == "load": result = service.load(plan)
            else:
                if not args.run_id: parser.error("--run-id is required for publish")
                result = service.publish(args.run_id, plan)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        print(f"Operation did not complete ({type(error).__name__}). Check sources, reviews, configuration and connection status; active content was not automatically replaced.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
