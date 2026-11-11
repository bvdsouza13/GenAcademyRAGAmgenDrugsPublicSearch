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
    "chunking": ["tests/test_review_and_chunking.py", "tests/test_bulk_eligibility.py", "tests/test_bulk_coverage.py"],
    "indexing": ["tests/test_indexing.py"],
    "search": ["tests/test_retrieval.py", "tests/test_global_search.py", "tests/test_search_artifacts.py"],
    "teaching": ["tests/test_teaching.py"],
    "ui": ["tests/test_app_flows.py", "tests/test_search_experience.py", "tests/test_admin_library_experience.py", "tests/test_chunk_experience.py", "tests/test_user_errors.py"],
    "integration": ["tests/test_service.py", "tests/test_source_import.py", "tests/test_library_build.py"],
    "evaluation": ["tests/test_evaluations.py", "tests/test_evaluation_metrics.py", "tests/test_chunk_experiments.py"],
    "demo": ["tests/test_demo.py", "tests/test_demo_navigation.py"],
    "regression": ["tests/test_regression_indexing.py", "tests/test_regression_corpus.py",
                   "tests/test_regression_evidence.py", "tests/test_regression_ui.py"],
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature", choices=["all", *GROUPS], nargs="?", default="all")
    args = parser.parse_args()
    targets = ["tests"] if args.feature == "all" else GROUPS[args.feature]
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *targets], cwd=ROOT)

if __name__ == "__main__":
    raise SystemExit(main())
