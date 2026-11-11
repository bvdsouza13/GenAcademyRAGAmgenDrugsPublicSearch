"""Synthetic fault injection for staging, publication and transport failures."""
import copy
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
import sqlite3
import tomllib
from urllib.error import HTTPError

import pytest

from amgen_explorer.config import AppConfig
import amgen_explorer.connectivity as connectivity
import amgen_explorer.indexing as indexing
from amgen_explorer.indexing import atomic_json
from test_indexing import FakeDocuments, plan, service


@pytest.fixture
def config(tmp_path):
    # Construct settings without opening the user's environment or secrets file.
    settings_path = Path(__file__).resolve().parents[1] / "config/app.toml"
    settings = tomllib.loads(settings_path.read_text())
    settings["pinecone"]["batch_size"] = 1
    return AppConfig(settings, tmp_path, "synthetic-key", "synthetic-key")


@pytest.mark.parametrize("operation", ["activate", "rollback", "ingest"])
def test_swapped_valid_run_manifest_cannot_select_a_different_corpus(config, plan, operation):
    index = service(config, FakeDocuments())
    first = index.ingest(plan)
    index.activate(first["run_id"], plan)
    active_before = config.path("active_corpus_manifest").read_bytes()
    changed = copy.deepcopy(plan)
    changed.chunks = changed.chunks[:1]
    changed.fingerprint = "e" * 64
    second = index.ingest(changed)
    # Both manifests are internally valid; the wrong filename is the corruption.
    atomic_json(index._run_path(first["run_id"]), second)

    with pytest.raises(ValueError, match="identity"):
        if operation == "activate":
            index.activate(first["run_id"], plan)
        elif operation == "rollback":
            index.rollback(first["run_id"])
        else:
            index.ingest(plan)
    assert config.path("active_corpus_manifest").read_bytes() == active_before


@pytest.mark.parametrize("failure", [IncompleteRead(b"synthetic-private-response", 100),
                                      BadStatusLine("synthetic-private-response"),
                                      TimeoutError("synthetic-private-response")])
def test_transport_failure_is_sanitized_and_retryable(monkeypatch, failure):
    class TruncatedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise failure

    class Opener:
        def open(self, *args, **kwargs):
            return TruncatedResponse()

    monkeypatch.setattr(connectivity, "build_opener", lambda *args: Opener())
    with pytest.raises(connectivity.ProviderError) as error:
        connectivity.request_json("https://example.invalid")
    assert error.value.retryable
    assert "synthetic-private-response" not in str(error.value)


@pytest.mark.parametrize("status,retryable", [(408, True), (429, True), (503, True), (400, False), (401, False), (403, False)])
def test_http_failures_have_explicit_retry_classification(monkeypatch, status, retryable):
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError("https://example.invalid", status, "synthetic-private-error", {}, None)

    monkeypatch.setattr(connectivity, "build_opener", lambda *args: Opener())
    with pytest.raises(connectivity.ProviderError) as error:
        connectivity.request_json("https://example.invalid")
    assert error.value.status == status
    assert error.value.retryable is retryable
    assert "synthetic-private-error" not in str(error.value)


@pytest.mark.parametrize("status,expected_attempts", [(429, 4), (503, 4), (None, 4), (403, 1)])
def test_upload_failure_is_bounded_and_preserves_active_corpus(config, plan, status, expected_attempts):
    fake = FakeDocuments()
    index = service(config, fake)
    first = index.ingest(plan)
    index.activate(first["run_id"], plan)
    active_before = config.path("active_corpus_manifest").read_bytes()
    changed = copy.deepcopy(plan)
    changed.fingerprint = "e" * 64
    attempts = []

    def fail(namespace, documents):
        attempts.append(namespace)
        raise connectivity.ProviderError("Synthetic", status)

    fake.upsert = fail
    with pytest.raises(connectivity.ProviderError):
        index.ingest(changed)
    assert len(attempts) == expected_attempts
    assert config.path("active_corpus_manifest").read_bytes() == active_before
    failed = indexing.read_json(index._run_path(index.preview(changed)["run_id"]))
    assert failed["status"] == "failed"
    assert failed["succeeded"] == 0
    assert failed["failed_ids"] == ["chunk-1", "chunk-2"]


def test_keyboard_interrupt_releases_lock_and_resumes_committed_batch(config, plan):
    fake = FakeDocuments()
    index = service(config, fake)

    def interrupt(progress):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        index.ingest(plan, on_progress=interrupt)
    resumed = index.ingest(plan)
    assert resumed["status"] == "verified"
    assert resumed["succeeded"] == 2
    assert fake.writes == [["chunk-1"], ["chunk-2"]]
    assert index.active() is None


def test_atomic_publication_failure_keeps_previous_active_and_releases_lock(config, plan, monkeypatch):
    index = service(config, FakeDocuments())
    first = index.ingest(plan)
    index.activate(first["run_id"], plan)
    active_path = config.path("active_corpus_manifest")
    active_before = active_path.read_bytes()
    changed = copy.deepcopy(plan)
    changed.fingerprint = "e" * 64
    second = index.ingest(changed)
    replace = indexing.os.replace

    def fail_active_replace(source, destination):
        if Path(destination) == active_path:
            raise OSError("Synthetic disk failure")
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(indexing.os, "replace", fail_active_replace)
        with pytest.raises(OSError, match="Synthetic disk failure"):
            index.activate(second["run_id"], changed)
    assert active_path.read_bytes() == active_before
    assert not list(active_path.parent.glob(".candidate-*"))
    assert index.activate(second["run_id"], changed)["run_id"] == second["run_id"]


def test_corrupt_checkpoint_fails_before_cloud_and_preserves_active(config, plan):
    fake = FakeDocuments()
    index = service(config, fake)
    first = index.ingest(plan)
    index.activate(first["run_id"], plan)
    active_before = config.path("active_corpus_manifest").read_bytes()
    checked_before, writes_before = fake.checked, copy.deepcopy(fake.writes)
    database = config.path("ingestion_database")
    database.write_bytes(b"synthetic corrupt sqlite file")
    with pytest.raises(sqlite3.DatabaseError):
        index.ingest(plan)
    assert config.path("active_corpus_manifest").read_bytes() == active_before
    assert fake.checked == checked_before
    assert fake.writes == writes_before


@pytest.mark.parametrize("target", ["manifest", "records", "active"])
def test_truncated_json_blocks_publication_without_replacing_active(config, plan, target):
    index = service(config, FakeDocuments())
    run = index.ingest(plan)
    index.activate(run["run_id"], plan)
    paths = {"manifest": index._run_path(run["run_id"]),
             "records": config.root / run["records_path"],
             "active": config.path("active_corpus_manifest")}
    paths[target].write_text('{"truncated":')
    active_before = config.path("active_corpus_manifest").read_bytes()
    with pytest.raises(ValueError):
        index.activate(run["run_id"], plan)
    assert config.path("active_corpus_manifest").read_bytes() == active_before
