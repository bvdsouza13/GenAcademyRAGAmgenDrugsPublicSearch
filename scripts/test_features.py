#!/usr/bin/env python3
"""Run individual feature suites without credentials or network access."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "connectivity": ["tests/test_connectivity.py"],
    "configuration": ["tests/test_config.py", "tests/test_pinecone_setup.py"],
    "xml": ["tests/test_xml_pipeline.py"],
    "chunking": ["tests/test_review_and_chunking.py"],
    "indexing": ["tests/test_indexing.py"],
    "search": ["tests/test_retrieval.py"],
    "teaching": ["tests/test_teaching.py"],
    "ui": ["tests/test_app_flows.py"],
    "integration": ["tests/test_service.py"],
    "evaluation": ["tests/test_evaluations.py"],
    "demo": ["tests/test_demo.py", "tests/test_demo_navigation.py"],
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature", choices=["all", *GROUPS], nargs="?", default="all")
    args = parser.parse_args()
    targets = ["tests"] if args.feature == "all" else GROUPS[args.feature]
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *targets], cwd=ROOT)

if __name__ == "__main__":
    raise SystemExit(main())
