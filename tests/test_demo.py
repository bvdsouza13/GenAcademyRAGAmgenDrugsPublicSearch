"""Portable prepared-demo provenance and real Streamlit navigation checks."""
import json
from pathlib import Path
import shutil
import socket
import sqlite3

import pytest
import requests
from streamlit.testing.v1 import AppTest

from amgen_explorer.demo import DemoUnavailable, FIXTURE, ROOT, load_example

PDF = 'repatha_not_made_with_natural_rubber_latex_prescribing_information.pdf'


@pytest.fixture
def portable_root(tmp_path):
    for relative in (FIXTURE, 'XML/AmgenProducts.xml', f'Documents/{PDF}'):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def change_fixture(root, change):
    path = root / FIXTURE
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_portable_example_checks_real_pdf_xml_quote_and_spans(portable_root):
    example = load_example(portable_root)
    ref = example.citation
    assert ref['supporting_quote'] in ref['source_text']
    assert ref['source_text'] in example.chunk_text
    assert 'PCSK9' in example.prepared['answer']
    assert ref['page_start'] == ref['page_end'] == 10
    assert ref['block_ids'][0] in example.canonical_xml
    assert example.page_image().startswith(b'\x89PNG')
    assert not list(portable_root.rglob('*.sqlite*'))
    fixture = (portable_root / FIXTURE).read_text()
    for forbidden in ('namespace', 'review_state', 'review_hash', 'host', '/Users/', 'api_key'):
        assert forbidden not in fixture.lower()


@pytest.mark.parametrize('relative', [FIXTURE, 'XML/AmgenProducts.xml', f'Documents/{PDF}'])
def test_missing_included_source_fails_closed(portable_root, relative):
    (portable_root / relative).unlink()
    with pytest.raises(DemoUnavailable, match='missing, changed'):
        load_example(portable_root)


@pytest.mark.parametrize('relative', ['XML/AmgenProducts.xml', f'Documents/{PDF}'])
def test_changed_source_bytes_fail_closed(portable_root, relative):
    path = portable_root / relative
    path.write_bytes(path.read_bytes() + b'\nchanged')
    with pytest.raises(DemoUnavailable, match='missing, changed'):
        load_example(portable_root)


@pytest.mark.parametrize('change', [
    lambda d: d['citation'].update(supporting_quote='A quote that is absent.'),
    lambda d: d['citation'].update(source_text='Changed passage'),
    lambda d: d['citation'].update(page_start=9),
    lambda d: d['citation'].update(document_id='another-document'),
    lambda d: d['citation'].update(filename='../outside.pdf'),
    lambda d: d['source_spans'][0].update(start=455),
    lambda d: d['source_spans'][0].update(block_start=-1),
    lambda d: d['source_spans'][0].update(page=9),
    lambda d: d.update(source_spans=[]),
])
def test_modified_citation_quote_or_span_fails_closed(portable_root, change):
    change_fixture(portable_root, change)
    with pytest.raises(DemoUnavailable):
        load_example(portable_root)


@pytest.fixture
def demo_app(monkeypatch, portable_root):
    import ui.demo
    for key in ('OPENAI_API_KEY', 'PINECONE_API_KEY', 'PINECONE_HOST'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ui.demo, 'load_example', lambda: load_example(portable_root))
    network_calls = []
    def no_network(*args, **kwargs):
        network_calls.append('network')
        raise AssertionError('Demo attempted a network call')
    monkeypatch.setattr(requests.Session, 'request', no_network)
    monkeypatch.setattr(socket, 'create_connection', no_network)
    monkeypatch.setattr(sqlite3, 'connect', no_network)
    at = AppTest.from_string('''
import streamlit as st
from ui.common import style
from ui.demo import render
class NoServices:
    def __getattr__(self, name):
        st.session_state.setdefault('service_calls', []).append(name)
        raise AssertionError('Prepared tour accessed service: ' + name)
style()
st.session_state.setdefault('service_calls', [])
render(NoServices(), None, None)
''', default_timeout=15)
    return at, network_calls, portable_root


def click(at, key):
    at.button(key=key).click().run()
    assert not at.exception


def test_all_steps_back_quiz_and_restart_have_zero_service_or_network_calls(demo_app):
    at, network_calls, root = demo_app
    at.run()
    assert not at.exception
    assert at.button(key='demo_back').disabled
    assert any('Prepared source-backed example' in x.value for x in at.info)
    expected = ('canonical XML', 'each chunk', 'its evidence', 'passage says')
    for heading in expected:
        click(at, 'demo_next')
        assert any(heading in x.value for x in at.subheader)
    assert at.button(key='demo_next').disabled
    assert at.button(key='demo_check').disabled
    at.radio(key='demo_answer').set_value(1).run()
    click(at, 'demo_check')
    assert any('Look again' in x.value for x in at.info)
    at.radio(key='demo_answer').set_value(0).run()
    assert not at.success
    click(at, 'demo_check')
    assert any('Correct' in x.value for x in at.success)
    click(at, 'demo_back')
    assert at.session_state['demo_step'] == 3
    click(at, 'demo_next')
    click(at, 'demo_restart')
    assert at.session_state['demo_step'] == 0
    for _ in range(4):
        click(at, 'demo_next')
    assert at.radio(key='demo_answer').value is None
    assert not at.success
    assert not at.session_state['service_calls']
    assert not network_calls
    assert not list(root.rglob('*.sqlite*'))


def test_exit_returns_to_catalog_and_clears_only_demo_query(demo_app):
    at, network_calls, _ = demo_app
    at.query_params['demo'] = '1'
    at.query_params['keep'] = 'yes'
    at.run()
    click(at, 'demo_exit')
    assert at.session_state['nav'] == 'Explore medicines'
    assert 'demo' not in at.query_params
    assert at.query_params['keep'] == 'yes'
    assert not at.session_state['service_calls'] and not network_calls


@pytest.mark.parametrize('change', ['missing', 'changed'])
def test_source_changes_during_tour_hide_prepared_content(demo_app, change):
    at, network_calls, root = demo_app
    at.run()
    pdf = root / 'Documents' / PDF
    if change == 'missing':
        pdf.unlink()
    else:
        pdf.write_bytes(pdf.read_bytes() + b'changed')
    click(at, 'demo_next')
    assert any('could not be verified' in x.value for x in at.warning)
    assert not at.code and not at.radio
    click(at, 'demo_restart_missing')
    assert at.session_state['demo_step'] == 0
    click(at, 'demo_exit_missing')
    assert at.session_state['nav'] == 'Explore medicines'
    assert not at.session_state['service_calls'] and not network_calls
