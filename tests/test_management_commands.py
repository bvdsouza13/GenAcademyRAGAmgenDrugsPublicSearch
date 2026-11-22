"""Destructive/recovery operations are separate explicit CLI actions."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import scripts.manage_corpus as cli


@pytest.mark.parametrize('command,method,kwargs',[
    ('verify-library','verify_library',{'run_id':'chosen','repair':False}),
    ('repair-library','verify_library',{'run_id':'chosen','repair':True}),
    ('readiness','check_readiness',{'require_generation':True}),
    ('recover-xml','recover_working_xml',{}),
    ('recoverable-versions','list_recoverable_versions',{}),
])
def test_explicit_management_action(monkeypatch,command,method,kwargs):
    operation=Mock(return_value={'ok':True})
    service=SimpleNamespace(chunk_config=Mock(return_value=None),**{method:operation})
    monkeypatch.setattr(cli,'ExplorerService',lambda:service)
    monkeypatch.setattr(sys,'argv',['manage_corpus.py',command,'--run-id','chosen'])
    assert cli.main()==0
    operation.assert_called_once_with(**kwargs)
