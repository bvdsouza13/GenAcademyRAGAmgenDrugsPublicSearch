#!/usr/bin/env python3
"""Explicit live checks of published search and optional OpenAI explanations.

No review changes, upserts, publication or deletions. --generate uses OpenAI.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amgen_explorer.service import ExplorerService, atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Also call OpenAI for a cited explanation per published source.")
    parser.add_argument("--output", type=Path, default=ROOT / "output/live-smoke.json")
    args = parser.parse_args()
    results = {"checks": [], "generated": args.generate}
    try:
        service = ExplorerService()
        active = service.active()
        if not active:
            raise ValueError("No published corpus.")
        corpus = service._pinned_corpus(active["xml_hash"])
        results.update(namespace=active["namespace"], xml_hash=active["xml_hash"])
        for doc in corpus.documents:
            if doc.id not in active["document_ids"]:
                continue
            question = "What target does this medicine bind to, according to section 12.1?"
            start = time.monotonic()
            evidence = service._evidence(question, doc.product_id, doc.id)
            if not evidence or not evidence.passages:
                raise ValueError("A published source did not return verified evidence.")
            row = {"document_id": doc.id, "product_id": doc.product_id,
                   "verified_passages": len(evidence.passages), "question": question}
            if args.generate:
                response = service.answer(question, doc.product_id, document_id=doc.id)
                row.update(answer=response.answer, abstained=response.abstained,
                           citations=response.citations, usage=response.usage)
                for citation in response.citations:
                    assert citation["document_id"] == doc.id
                    assert citation["document_sha256"] == doc.sha256
                    assert citation["xml_hash"] == corpus.xml_hash
                    assert citation["supporting_quote"] in citation["text"]
                    assert 1 <= citation["page_start"] <= citation["page_end"] <= doc.page_count
                if not response.abstained and not response.citations:
                    raise ValueError("An answer had no source citations.")
            row["seconds"] = round(time.monotonic() - start, 3)
            results["checks"].append(row)
            print(f"{doc.id}: {len(evidence.passages)} verified passages; {row['seconds']} seconds", flush=True)
        results["status"] = "passed"
    except Exception as error:
        # Do not expose provider bodies or credential-bearing exception messages.
        results.update(status="failed", error_type=type(error).__name__,
                       error="A live source/search/generation check failed. Check connections and the published source scope.")
    atomic_json(args.output.resolve(), results)
    print(f"Live smoke: {results['status']}. Report: {args.output}")
    return 0 if results["status"] == "passed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
