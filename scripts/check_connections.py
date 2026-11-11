#!/usr/bin/env python3
"""Explicit read-only cloud checks. Never prints credentials or remote bodies."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amgen_explorer.config import load_config
from amgen_explorer.connectivity import check_connections


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--secrets', type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_connections(load_config(args.config, args.secrets))
    except (ValueError, OSError, TypeError):
        print('Configuration could not be loaded; check TOML syntax and local permissions.', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0 if all(service.get('ok') for service in result.values()) else 1

if __name__ == '__main__':
    raise SystemExit(main())
