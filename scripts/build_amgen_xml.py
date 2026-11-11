#!/usr/bin/env python3
"""Local canonical XML build. Does not upload or clinically approve content."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amgen_explorer.extraction import build_corpus, CorpusBuildError
from amgen_explorer.xml_store import load_corpus, validate_schema, validate_source_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    output = args.root / 'XML' / 'AmgenProducts.xml'
    if args.validate_only:
        corpus = load_corpus(output)
        checks = validate_source_files(corpus, args.root / 'Documents')
        print(json.dumps({**checks, 'schema_valid': validate_schema(output), 'documents': len(corpus.documents), 'blocks': len(corpus.blocks)}))
    else:
        try:
            report = build_corpus(args.root / 'Documents', output)
        except CorpusBuildError as error:
            print(json.dumps(asdict(error.report), indent=2))
            raise SystemExit(1)
        print(json.dumps(asdict(report), indent=2))

if __name__ == '__main__': main()
