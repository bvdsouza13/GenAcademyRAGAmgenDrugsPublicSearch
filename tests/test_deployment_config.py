"""Publishing must start Streamlit's HTTP server, not execute the UI as a script."""
from pathlib import Path
import tomllib
from amgen_explorer.hosted_startup import streamlit_command


def test_publishing_starts_streamlit_on_the_preview_port():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".replit").read_text())
    command = config["deployment"]["run"]
    assert command == ["python", "scripts/start_streamlit.py"]
    assert (root / command[1]).is_file()
    server = streamlit_command({})
    assert server[1:4] == ["-m", "streamlit", "run"]
    assert Path(server[4]) == root / "app.py"
    assert server[server.index("--server.address") + 1] == "0.0.0.0"
    assert server[server.index("--server.port") + 1] == "5000"
    assert server[server.index("--server.headless") + 1] == "true"
