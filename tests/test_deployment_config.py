"""Publishing must start Streamlit's HTTP server, not execute the UI as a script."""
from pathlib import Path
import tomllib


def test_publishing_starts_streamlit_on_the_preview_port():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".replit").read_text())
    command = config["deployment"]["run"]
    assert command[:5] == ["python", "-m", "streamlit", "run", "app.py"]
    assert command[command.index("--server.address") + 1] == "0.0.0.0"
    assert command[command.index("--server.port") + 1] == "5000"
    assert command[command.index("--server.headless") + 1] == "true"
    assert (root / command[4]).is_file()
