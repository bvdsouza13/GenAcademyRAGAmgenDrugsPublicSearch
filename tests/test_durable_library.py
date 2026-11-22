import copy
import hashlib
import json
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from amgen_explorer import durable_library as storage


class MemoryDatabase:
    def __init__(self):
        self.row = None
        self.reviews = {}
        self.batches = {}

    def connect(self):
        return MemoryConnection(self)


class MemoryConnection:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=None):
        normalized = " ".join(query.casefold().split())
        if normalized.startswith("select generation, objects, active_pointer"):
            if self.database.row is None:
                return MemoryResult(None)
            row = self.database.row
            return MemoryResult((row["generation"], copy.deepcopy(row["objects"]),
                                 copy.deepcopy(row["active_pointer"])))
        if normalized.startswith("insert into amgen_library_storage"):
            objects, pointer = params
            self.database.row = {
                "generation": 1,
                "objects": json.loads(objects),
                "active_pointer": json.loads(pointer) if pointer is not None else None,
            }
            return MemoryResult(None)
        if normalized.startswith("update amgen_library_storage"):
            generation, objects, pointer = params
            self.database.row = {
                "generation": generation,
                "objects": json.loads(objects),
                "active_pointer": json.loads(pointer) if pointer is not None else None,
            }
            return MemoryResult(None)
        if normalized.startswith("insert into amgen_review_decisions"):
            row_id = params[0] if len(params) == 8 else max(self.database.reviews, default=0) + 1
            values = tuple(params) if len(params) == 8 else (row_id, *params)
            self.database.reviews.setdefault(row_id, values)
            return MemoryResult(None)
        if normalized.startswith("select id,scope_hash,block_id,decision,reviewer,note,recorded_at,scope_json"):
            return MemoryResult(self.database.reviews.get(params[0]))
        if normalized.startswith("select decision,reviewer,note,recorded_at,scope_json from amgen_review_decisions"):
            matches = [row for row in self.database.reviews.values() if row[1] == params[0]]
            row = max(matches, key=lambda item: item[0]) if matches else None
            return MemoryResult(tuple(row[3:]) if row else None)
        if normalized.startswith("select scope_hash,decision,reviewer,note,recorded_at,scope_json from amgen_review_decisions"):
            latest = {}
            for row in self.database.reviews.values():
                if row[1] not in latest or row[0] > latest[row[1]][0]:
                    latest[row[1]] = row
            return MemoryResultRows([
                (row[1], *row[3:]) for row in latest.values()
            ])
        if normalized.startswith("select setval("):
            return MemoryResult(None)
        if normalized.startswith("insert into amgen_ingestion_batches"):
            self.database.batches.setdefault((params[0], params[1]), tuple(params))
            return MemoryResult(None)
        if normalized.startswith("select run,batch,attempts,done from amgen_ingestion_batches"):
            return MemoryResult(self.database.batches.get((params[0], params[1])))
        raise AssertionError(f"Unexpected SQL in fake database: {query}")


class MemoryResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class MemoryResultRows(MemoryResult):
    def fetchall(self):
        return self.row


class MemoryObjects:
    def __init__(self):
        self.objects = {}

    def upload_from_filename(self, key, filename):
        self.objects[key] = Path(filename).read_bytes()

    def download_to_filename(self, key, filename):
        Path(filename).write_bytes(self.objects[key])


def make_config(root):
    paths = {
        "active_corpus_manifest": "data/active-corpus.json",
        "corpus_dir": "data/corpora",
        "review_database": "data/review.sqlite",
        "ingestion_database": "data/ingestion.sqlite",
    }
    return SimpleNamespace(
        root=Path(root),
        path=lambda name: Path(root) / paths[name],
    )


def make_local_library(root):
    files = {
        "Documents/label.pdf": b"source-pdf-v1",
        "XML/AmgenProducts.xml": b"working-xml-v1",
        "data/corpora/xml-hash/AmgenProducts.xml": b"pinned-xml-v1",
        "data/corpora/xml-hash/document-hash.pdf": b"pinned-pdf-v1",
        "data/manifests/run.json": b'{"status":"verified"}',
        "data/manifests/run.chunks.json": b'[]',
        "data/manifests/run.global-rrf-v1.sqlite": b"immutable-search-index",
    }
    for relative, payload in files.items():
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    review_db = sqlite3.connect(Path(root) / "data/review.sqlite")
    review_db.execute(
        "CREATE TABLE reviews (id INTEGER PRIMARY KEY, scope_hash TEXT NOT NULL, "
        "block_id TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL, "
        "note TEXT NOT NULL, recorded_at TEXT NOT NULL, scope_json TEXT NOT NULL)"
    )
    review_db.execute(
        "INSERT INTO reviews VALUES (1,?,?,?,?,?,?,?)",
        ("scope", "block", "accepted", "reviewer", "note", "2026-01-01T00:00:00+00:00", "{}"),
    )
    review_db.commit()
    review_db.close()
    ingestion_db = sqlite3.connect(Path(root) / "data/ingestion.sqlite")
    ingestion_db.execute(
        "CREATE TABLE batches (run TEXT, batch TEXT, attempts INTEGER DEFAULT 0, "
        "done INTEGER DEFAULT 0, PRIMARY KEY(run,batch))"
    )
    ingestion_db.execute("INSERT INTO batches VALUES ('run','batch',2,1)")
    ingestion_db.commit()
    ingestion_db.close()
    return files


def test_seed_and_restore_preserve_pinned_assets_and_sql_pointer(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = make_local_library(tmp_path)
    pointer = {"run_id": "a" * 64, "status": "verified", "xml_hash": "b" * 64}
    pointer_path = config.path("active_corpus_manifest")
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer))

    database, objects = MemoryDatabase(), MemoryObjects()
    connect = database.connect
    monkeypatch.setattr(storage, "_validate_active", lambda _config, _pointer: None)
    seeded = storage.seed_from_local(config, object_client=objects, connect=connect)

    assert seeded["asset_count"] == 7
    assert seeded["active_run_id"] == pointer["run_id"]
    assert seeded["reviews"] == 1
    assert seeded["ingestion_batches"] == 1
    assert database.row["active_pointer"] == pointer
    assert "data/review.sqlite" not in database.row["objects"]
    assert "data/ingestion.sqlite" not in database.row["objects"]
    assert database.reviews[1][2:4] == ("block", "accepted")
    assert database.batches[("run", "batch")] == ("run", "batch", 2, True)

    # Simulate a fresh deployment with files missing and an old/bad active pointer.
    for relative in files:
        if storage._is_library_asset(relative):
            (tmp_path / relative).unlink()
    pointer_path.write_text('{"run_id":"stale"}')
    restored = storage.restore_from_app_storage(config, object_client=objects, connect=connect)

    assert restored["restored_count"] == 7
    assert pointer_path.read_text() == json.dumps(pointer, ensure_ascii=False, indent=2)
    for relative in files:
        if storage._is_library_asset(relative):
            assert (tmp_path / relative).read_bytes() == files[relative]


def test_restore_fails_closed_when_a_remote_asset_is_corrupt(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    files = make_local_library(tmp_path)
    pointer_path = config.path("active_corpus_manifest")
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    active = {"run_id": "a" * 64, "status": "verified", "xml_hash": "b" * 64}
    pointer_path.write_text(json.dumps(active))
    database, objects = MemoryDatabase(), MemoryObjects()
    monkeypatch.setattr(storage, "_validate_active", lambda _config, _pointer: None)
    storage.seed_from_local(config, object_client=objects, connect=database.connect)

    target = "Documents/label.pdf"
    entry = database.row["objects"][target]
    objects.objects[entry["object_key"]] = b"tampered"
    (tmp_path / target).unlink()
    previous_pointer = {"run_id": "c" * 64, "status": "verified", "xml_hash": "d" * 64}
    pointer_path.write_text(json.dumps(previous_pointer))

    with pytest.raises(storage.DurableStorageError, match="checksum"):
        storage.restore_from_app_storage(config, object_client=objects, connect=database.connect)
    assert not (tmp_path / target).exists()
    assert json.loads(pointer_path.read_text()) == previous_pointer


def test_repeated_seed_refuses_to_replace_existing_remote_library(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    make_local_library(tmp_path)
    database, objects = MemoryDatabase(), MemoryObjects()
    storage.seed_from_local(config, object_client=objects, connect=database.connect)
    before = copy.deepcopy(database.row)

    with pytest.raises(storage.DurableStorageError, match="already initialized"):
        storage.seed_from_local(config, object_client=objects, connect=database.connect)
    assert database.row == before


def test_library_asset_allowlist_excludes_mutable_local_sqlite_files():
    assert storage._is_library_asset("Documents/label.pdf")
    assert storage._is_library_asset("data/manifests/run.global-rrf-v1.sqlite")
    assert not storage._is_library_asset("data/review.sqlite")
    assert not storage._is_library_asset("data/ingestion.sqlite")
    assert not storage._is_library_asset("data/active-corpus.json")
    assert not storage._is_library_asset("../outside.pdf")


def test_managed_review_store_keeps_the_existing_review_fingerprint(monkeypatch):
    from amgen_explorer.models import Corpus, Product, SourceBlock
    from amgen_explorer.review import ManagedReviewStore

    block = SourceBlock(
        id="block-1", product_id="product-1", document_id="doc-1",
        document_sha256="a" * 64, text="Source passage", section_id="section-1",
        section_title="Section", section_kind="fullPrescribingInformation",
        page_start=1, page_end=1,
        content_hash=hashlib.sha256(b"Source passage").hexdigest(),
        spans=[{"page": 1, "start": 0, "end": 14}],
    )
    corpus = Corpus(Path("unused.xml"), "b" * 64, [Product("product-1", "Example")], [], [block])
    database = MemoryDatabase()
    monkeypatch.setattr(storage, "database_connection", database.connect)
    reviews = ManagedReviewStore()

    reviews.record(block, "accepted", "Test reviewer", "source checked")

    assert reviews.status(block) == "accepted"
    statuses, fingerprint = reviews.snapshot(corpus)
    assert statuses == {"block-1": "accepted"}
    assert len(fingerprint) == 64


def test_managed_ingestion_adapter_maps_sqlite_checkpoint_statements():
    from amgen_explorer.indexing import _ManagedIngestionConnection

    class Recorder:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((query, params))
            return MemoryResult(None)

    connection = Recorder()
    managed = _ManagedIngestionConnection(connection)
    managed.execute("INSERT OR IGNORE INTO batches(run,batch) VALUES (?,?)", ("run", "batch"))
    managed.execute("UPDATE batches SET done=0 WHERE run=? AND batch=?", ("run", "batch"))
    managed.execute("INSERT OR REPLACE INTO job_lock VALUES (?,?,?)", ("target", 7, 1.0))

    assert "amgen_ingestion_batches" in connection.calls[0][0]
    assert "ON CONFLICT (run,batch) DO NOTHING" in connection.calls[0][0]
    assert "done=FALSE" in connection.calls[1][0]
    assert "amgen_ingestion_job_lock" in connection.calls[2][0]
    assert "ON CONFLICT (target) DO UPDATE" in connection.calls[2][0]
    assert all("?" not in query for query, _ in connection.calls)
