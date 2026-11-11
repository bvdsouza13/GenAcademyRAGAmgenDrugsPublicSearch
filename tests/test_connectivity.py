import json
from urllib.error import HTTPError, URLError
import pytest
import amgen_explorer.connectivity as connectivity
from test_indexing import config


def test_connection_errors_are_sanitized(config,monkeypatch):
    secret='never-disclose-this'; config.pinecone_api_key=secret; config.openai_api_key=secret
    class BadDocuments:
        def __init__(self,*args,**kwargs):pass
        def check(self): raise ValueError('reflected '+secret)
    monkeypatch.setattr(connectivity,'DocumentsClient',BadDocuments)
    def fail(*args,**kwargs):raise connectivity.ProviderError('OpenAI',401)
    monkeypatch.setattr(connectivity,'request_json',fail)
    result=connectivity.check_connections(config)
    assert not result['pinecone']['ok'] and not result['openai']['ok']
    assert secret not in json.dumps(result)


def test_no_remote_errors_or_redirects_are_echoed(monkeypatch):
    class BadOpener:
        def open(self,*args,**kwargs):
            raise HTTPError('https://secret.example',401,'secret body',{},None)
    monkeypatch.setattr(connectivity,'build_opener',lambda *args:BadOpener())
    with pytest.raises(connectivity.ProviderError) as error:
        connectivity.request_json('https://api.openai.com/v1/models',method='GET')
    assert 'secret' not in str(error.value)
    assert error.value.status==401 and not error.value.retryable


def test_empty_credentials_fail_before_provider(config,monkeypatch):
    config.pinecone_api_key=None;config.openai_api_key=None
    calls=[]
    monkeypatch.setattr(connectivity,'request_json',lambda *args,**kwargs:calls.append(args))
    result=connectivity.check_connections(config)
    assert not calls
    assert not result['pinecone']['ok'] and not result['openai']['ok']
