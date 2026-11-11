"""Test the real entry point: direct demo links must bypass live services."""
from pathlib import Path
from types import SimpleNamespace
import sys

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_direct_demo_link_bypasses_service_and_stays_on_step(monkeypatch):
    def forbidden():
        raise AssertionError('Demo must not construct a live service')
    monkeypatch.setitem(sys.modules, 'amgen_explorer.service', SimpleNamespace(ExplorerService=forbidden))
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20)
    at.query_params['demo'] = '1'
    at.run()
    assert not at.exception
    assert at.sidebar.radio(key='nav').value == 'Demo tour'
    assert any('No API keys' in c.value for c in at.caption)
    at.button(key='demo_next').click().run()
    at.run()
    assert not at.exception
    assert any('2 · Preserve' in h.value for h in at.subheader)
    assert not at.error


def test_sidebar_demo_and_exit_restore_catalog(monkeypatch):
    constructions = []
    def factory():
        constructions.append(True)
        return SimpleNamespace(corpus=lambda: None, active=lambda: None, inventory=lambda: [])
    monkeypatch.setitem(sys.modules, 'amgen_explorer.service', SimpleNamespace(ExplorerService=factory))
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
    assert not at.exception and len(constructions) == 1
    at.sidebar.radio(key='nav').set_value('Demo tour').run()
    assert not at.exception and len(constructions) == 1
    at.query_params['demo'] = '1'
    at.button(key='demo_exit').click().run()
    assert not at.exception and len(constructions) == 2
    assert at.sidebar.radio(key='nav').value == 'Explore medicines'
    assert 'demo' not in at.query_params


def test_demo_starts_with_no_live_database_or_transport(monkeypatch):
    import sqlite3
    import urllib.request
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('Demo cannot use database or network')
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20)
    at.query_params['demo'] = '1'
    at.run()
    assert not at.exception and not at.error
    assert at.button(key='demo_next')
