#!/usr/bin/env python3
"""Check local configuration offline; never create or contact cloud resources."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amgen_explorer.config import load_config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Run offline checks (the default).")
    parser.add_argument("--config", help="Settings TOML; relative paths resolve from the repository.")
    parser.add_argument("--secrets", help="Optional secrets TOML; never prints its contents.")
    parser.add_argument("--require-secrets", action="store_true", help="Fail if PINECONE_API_KEY is missing.")
    parser.add_argument("--require-chat", action="store_true", help="Require OPENAI_API_KEY and the chat model.")
    parser.add_argument("--require-host", action="store_true", help="Require a configured Pinecone index hostname.")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config, args.secrets)
        errors = cfg.validate(require_secrets=args.require_secrets,
                              require_chat=args.require_chat, require_host=args.require_host)
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    print("Offline configuration check — not live app readiness.")
    for name, value in (("PINECONE_API_KEY", cfg.pinecone_api_key), ("OPENAI_API_KEY", cfg.openai_api_key)):
        print(f"{name}: {'configured' if value else 'missing'}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for name in ("source_dir", "xml_template", "xml_output"):
        path = cfg.path(name)
        exists = path.is_dir() if name == "source_dir" else path.is_file()
        print(f"{name}: {path} ({'present' if exists else 'missing'})")
        if not exists:
            errors.append(f"Required source path is missing: {name}.")
    for name in ("review_database", "ingestion_database", "manifest_dir", "active_corpus_manifest"):
        path = cfg.path(name)
        print(f"{name}: {'present' if path.exists() else 'not created yet'}")
    pc, ai = cfg.settings["pinecone"], cfg.settings["openai"]
    print(f"Pinecone: {pc['index_name']} / {pc['cloud']} / {pc['region']} / {pc['embedding_model']}")
    print(f"Pinecone host: {'configured' if pc['index_host'] else 'not configured (expected before index creation)'}")
    print(f"OpenAI: {ai['api']} / {ai['model'] or 'model missing'}; account access not checked.")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    print("No network requests made. App, reviewed corpus, ingestion, and retrieval readiness are separate checks.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
