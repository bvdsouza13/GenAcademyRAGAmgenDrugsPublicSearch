from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_safe_local_error_is_actionable_but_provider_error_is_sanitized(tmp_path):
    path=tmp_path/'errors.py'
    path.write_text('''import streamlit as st
from ui.common import action
from amgen_explorer.errors import UserFacingError
def local(): raise UserFacingError("Missing registered source PDFs: alpha.pdf")
def provider(): raise RuntimeError("secret-value-must-not-appear")
action("Build",local)
action("Provider",provider)
''')
    at=AppTest.from_file(str(path)).run()
    assert not at.exception
    messages=' '.join(e.value for e in at.error)
    assert 'Missing registered source PDFs: alpha.pdf' in messages
    assert 'secret-value-must-not-appear' not in messages
