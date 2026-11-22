"""Production entrypoint: prepare private OIDC settings and start Streamlit."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amgen_explorer.hosted_startup import main

if __name__ == "__main__":
    raise SystemExit(main())
