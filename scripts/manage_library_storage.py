"""Explicitly seed or verify the Replit App Storage library cache."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amgen_explorer.config import load_config
from amgen_explorer.durable_library import (
    DurableStorageError,
    restore_from_app_storage,
    seed_from_local,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed-local", help="copy verified local library files into an empty App Storage manifest")
    commands.add_parser("verify-restore", help="restore and checksum every asset in the saved App Storage manifest")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        result = (seed_from_local(config) if args.command == "seed-local"
                  else restore_from_app_storage(config))
    except (DurableStorageError, ValueError, OSError):
        print("Library storage operation failed. Check App Storage, the development SQL schema, and local file integrity.")
        return 1
    print(f"Library storage {args.command} succeeded.")
    print(f"Assets: {result['asset_count']}; active run: {result.get('active_run_id') or 'none'}")
    if "restored_count" in result:
        print(f"Restored files: {result['restored_count']}; generation: {result['generation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
