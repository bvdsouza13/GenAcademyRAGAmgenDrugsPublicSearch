"""Verified App Storage mirror and PostgreSQL pointer for a pinned library.

The application's existing file-based library code continues to operate on a
local cache. In Replit storage mode, this module restores that cache from an
integrity manifest at startup and writes immutable assets before committing
active-pointer changes in PostgreSQL.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import copy
from typing import Any


STATE_TABLE = "amgen_library_storage"
_HEX = re.compile(r"[a-f0-9]{64}")
_KEEP_POINTER = object()
_RESTORED_ROOTS: dict[str, tuple[int, dict]] = {}
_ACTIVE_POINTERS: dict[str, dict | None] = {}


class DurableStorageError(RuntimeError):
    """A sanitized persistence or recovery failure safe to display to learners."""


def backend_enabled() -> bool:
    """Whether this process must restore/persist through Replit App Storage."""
    value = os.environ.get("AMGEN_STORAGE_BACKEND", "local").strip().casefold()
    if value in {"", "local", "disabled"}:
        return False
    if value in {"app_storage", "replit", "replit-app-storage"}:
        return True
    raise DurableStorageError("AMGEN_STORAGE_BACKEND must be local or app_storage.")


def _prefix() -> str:
    value = os.environ.get("AMGEN_STORAGE_PREFIX", "amgen-medicine-explorer/v1").strip()
    if (not value or value.startswith("/") or "\\" in value or ".." in value.split("/")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,150}", value)):
        raise DurableStorageError("The App Storage object prefix is invalid.")
    return value.rstrip("/")


def _relative_path(root: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise DurableStorageError("A library asset is outside the project or is not a regular file.")
    relative = resolved.relative_to(root.resolve()).as_posix()
    if not _is_library_asset(relative):
        raise DurableStorageError("A requested file is not part of the persistent library.")
    return relative


def _is_library_asset(relative: str) -> bool:
    """Keep source files, generated/pinned corpora and versioned library records."""
    path = PurePosixPath(relative)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False
    if parts[0] == "Documents":
        return len(parts) == 2 and path.suffix.casefold() == ".pdf"
    if parts[0] == "XML":
        return (relative == "XML/AmgenProducts.xml"
                or (len(parts) >= 3 and parts[1] == "snapshots" and path.suffix.casefold() == ".xml"))
    if parts[0] != "data":
        return False
    if relative == "data/active-corpus.json":
        return False  # The authoritative active pointer is in managed SQL.
    if path.name in {"review.sqlite", "ingestion.sqlite", "library.lock",
                     "ingestion.sqlite.lock", "review.sqlite-wal", "review.sqlite-shm"}:
        return False
    if path.name.startswith(".") or path.name.endswith((".lock", "-wal", "-shm")):
        return False
    # Search indexes are immutable, content-addressed files under manifests.
    if path.suffix.casefold() == ".sqlite":
        return len(parts) >= 3 and parts[1] == "manifests"
    return path.suffix.casefold() in {".json", ".pdf", ".xml"}


def _asset_paths(root: Path) -> list[Path]:
    paths: set[Path] = set()
    candidates = (root / "Documents", root / "XML", root / "data")
    for directory in candidates:
        if not directory.exists():
            continue
        if directory.is_symlink():
            raise DurableStorageError("A library asset directory must not be a symbolic link.")
        for path in directory.rglob("*"):
            if path.is_symlink():
                if _is_library_asset(path.relative_to(root).as_posix()):
                    raise DurableStorageError("A library asset must not be a symbolic link.")
                continue
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if _is_library_asset(relative):
                    paths.add(path)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class _AppStorageObjects:
    def __init__(self, client=None):
        if client is None:
            from replit.object_storage import Client
            client = Client()
        self.client = client

    def upload(self, key: str, path: Path) -> None:
        self.client.upload_from_filename(key, str(path))

    def download(self, key: str, path: Path) -> None:
        self.client.download_to_filename(key, str(path))


def _connect():
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise DurableStorageError("Replit SQL is unavailable; DATABASE_URL is not configured.")
    try:
        import psycopg
        return psycopg.connect(dsn, connect_timeout=10)
    except Exception:
        raise DurableStorageError("Unable to connect to the Replit SQL database.") from None


def database_connection():
    """Open a connection to the Replit-managed PostgreSQL database."""
    return _connect()


def _legacy_rows(path: Path, query: str) -> list[tuple]:
    if not path.is_file():
        return []
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as database:
            return database.execute(query).fetchall()
    except sqlite3.Error:
        # A SQLite file without the relevant table is an empty legacy store.
        try:
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as database:
                table = "reviews" if "reviews" in query else "batches"
                if database.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone() is None:
                    return []
        except sqlite3.Error:
            pass
        raise DurableStorageError("A local mutable-state database could not be read safely.") from None


def _migrate_sqlite_state(config, *, connect=_connect) -> dict:
    """Copy local review and interrupted-ingestion rows without deleting SQLite."""
    review_rows = _legacy_rows(
        config.path("review_database"),
        "SELECT id,scope_hash,block_id,decision,reviewer,note,recorded_at,scope_json FROM reviews ORDER BY id",
    )
    batch_rows = _legacy_rows(
        config.path("ingestion_database"),
        "SELECT run,batch,attempts,done FROM batches ORDER BY run,batch",
    )
    try:
        with connect() as database:
            with database.transaction():
                for row in review_rows:
                    database.execute(
                        "INSERT INTO amgen_review_decisions "
                        "(id,scope_hash,block_id,decision,reviewer,note,recorded_at,scope_json) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                        row,
                    )
                    saved = database.execute(
                        "SELECT id,scope_hash,block_id,decision,reviewer,note,recorded_at,scope_json "
                        "FROM amgen_review_decisions WHERE id=%s", (row[0],),
                    ).fetchone()
                    if tuple(saved or ()) != tuple(row):
                        raise DurableStorageError("Local review history conflicts with managed SQL; migration stopped.")
                if review_rows:
                    database.execute(
                        "SELECT setval(pg_get_serial_sequence('amgen_review_decisions','id'), "
                        "COALESCE((SELECT MAX(id) FROM amgen_review_decisions), 1), "
                        "EXISTS(SELECT 1 FROM amgen_review_decisions))"
                    )
                for row in batch_rows:
                    normalized = (row[0], row[1], row[2], bool(row[3]))
                    database.execute(
                        "INSERT INTO amgen_ingestion_batches (run,batch,attempts,done) "
                        "VALUES (%s,%s,%s,%s) ON CONFLICT (run,batch) DO NOTHING",
                        normalized,
                    )
                    saved = database.execute(
                        "SELECT run,batch,attempts,done FROM amgen_ingestion_batches "
                        "WHERE run=%s AND batch=%s", (row[0], row[1]),
                    ).fetchone()
                    if tuple(saved or ()) != normalized:
                        raise DurableStorageError("Local ingestion history conflicts with managed SQL; migration stopped.")
    except DurableStorageError:
        raise
    except Exception:
        raise DurableStorageError("Local mutable state could not be migrated to managed SQL.") from None
    return {"reviews": len(review_rows), "ingestion_batches": len(batch_rows)}


def _decode_json(value: Any, *, expected_type):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise DurableStorageError("The saved library state failed validation.") from None
    if not isinstance(value, expected_type):
        raise DurableStorageError("The saved library state failed validation.")
    return value


def _read_state(connect=_connect) -> dict | None:
    try:
        with connect() as connection:
            row = connection.execute(
                f"SELECT generation, objects, active_pointer FROM {STATE_TABLE} WHERE singleton = TRUE"
            ).fetchone()
    except DurableStorageError:
        raise
    except Exception:
        raise DurableStorageError(
            "The library storage database is unavailable or its schema is not installed."
        ) from None
    if row is None:
        return None
    generation, objects, active_pointer = row
    if type(generation) is not int or generation < 1:
        raise DurableStorageError("The saved library state failed validation.")
    objects = _decode_json(objects, expected_type=dict)
    if active_pointer is not None:
        active_pointer = _decode_json(active_pointer, expected_type=dict)
    for relative, entry in objects.items():
        if (not isinstance(relative, str) or not _is_library_asset(relative)
                or not isinstance(entry, dict) or entry.get("path") != relative
                or not isinstance(entry.get("object_key"), str)
                or not isinstance(entry.get("sha256"), str) or not _HEX.fullmatch(entry["sha256"])
                or entry["object_key"] != f"{_prefix()}/objects/{entry['sha256']}/{relative}"
                or type(entry.get("size")) is not int or entry["size"] < 0):
            raise DurableStorageError("The saved library inventory failed validation.")
    return {"generation": generation, "objects": objects, "active_pointer": active_pointer}


def active_pointer(config) -> dict | None:
    """Read the authoritative pointer from SQL when storage mode is enabled."""
    if not backend_enabled():
        return None
    key = str(config.root.resolve())
    if key in _ACTIVE_POINTERS:
        return copy.deepcopy(_ACTIVE_POINTERS[key])
    state = _read_state()
    if state is None:
        raise DurableStorageError("Persistent library storage is not initialized.")
    _ACTIVE_POINTERS[key] = copy.deepcopy(state["active_pointer"])
    return state["active_pointer"]


def _commit_state(updates: dict, active=_KEEP_POINTER, *, initialize=False,
                  connect=_connect) -> dict:
    try:
        with connect() as connection:
            with connection.transaction():
                row = connection.execute(
                    f"SELECT generation, objects, active_pointer FROM {STATE_TABLE} "
                    "WHERE singleton = TRUE FOR UPDATE"
                ).fetchone()
                if row is None:
                    if not initialize:
                        raise DurableStorageError("Persistent library storage is not initialized.")
                    objects = dict(updates)
                    pointer = None if active is _KEEP_POINTER else active
                    connection.execute(
                        f"INSERT INTO {STATE_TABLE} "
                        "(singleton, generation, objects, active_pointer, updated_at) "
                        "VALUES (TRUE, 1, %s::jsonb, %s::jsonb, now())",
                        (json.dumps(objects, ensure_ascii=False, sort_keys=True),
                         json.dumps(pointer, ensure_ascii=False, sort_keys=True) if pointer is not None else None),
                    )
                    return {"generation": 1, "objects": objects, "active_pointer": pointer}
                generation, saved_objects, saved_pointer = row
                if initialize:
                    raise DurableStorageError("Persistent library storage is already initialized; refusing to replace it.")
                objects = _decode_json(saved_objects, expected_type=dict)
                objects.update(updates)
                pointer = saved_pointer if active is _KEEP_POINTER else active
                connection.execute(
                    f"UPDATE {STATE_TABLE} SET generation = %s, objects = %s::jsonb, "
                    "active_pointer = %s::jsonb, updated_at = now() WHERE singleton = TRUE",
                    (generation + 1, json.dumps(objects, ensure_ascii=False, sort_keys=True),
                     json.dumps(pointer, ensure_ascii=False, sort_keys=True) if pointer is not None else None),
                )
                return {"generation": generation + 1, "objects": objects, "active_pointer": pointer}
    except DurableStorageError:
        raise
    except Exception:
        raise DurableStorageError("Unable to save the verified library state in Replit SQL.") from None


def _entry_for(path: Path, root: Path, objects: _AppStorageObjects) -> tuple[str, dict]:
    relative = _relative_path(root, path)
    sha, size = _sha256(path)
    key = f"{_prefix()}/objects/{sha}/{relative}"
    try:
        objects.upload(key, path)
        with tempfile.TemporaryDirectory(prefix="amgen-storage-check-") as temporary:
            check = Path(temporary) / "uploaded-file"
            objects.download(key, check)
            verified_sha, verified_size = _sha256(check)
            if (verified_sha, verified_size) != (sha, size):
                raise DurableStorageError("An uploaded library asset did not match its source checksum.")
    except DurableStorageError:
        raise
    except Exception:
        raise DurableStorageError("App Storage could not save and verify a library asset.") from None
    return relative, {"path": relative, "object_key": key, "sha256": sha, "size": size}


def sync_paths(config, paths=None, *, active=_KEEP_POINTER, object_client=None,
               connect=_connect) -> dict:
    """Write selected local files through to App Storage before saving inventory."""
    state = _read_state(connect=connect)
    if state is None:
        raise DurableStorageError("Persistent library storage is not initialized; migrate local files first.")
    root = config.root.resolve()
    candidates = _asset_paths(root) if paths is None else [Path(path) for path in paths]
    storage = _AppStorageObjects(object_client)
    updates = {}
    for path in candidates:
        if not path.exists():
            continue
        relative = _relative_path(root, path)
        sha, size = _sha256(path)
        existing = state["objects"].get(relative)
        if existing and (existing["sha256"], existing["size"]) == (sha, size):
            continue
        _, entry = _entry_for(path, root, storage)
        updates[relative] = entry
    if not updates and active is _KEEP_POINTER:
        return state
    saved = _commit_state(updates, active, connect=connect)
    _ACTIVE_POINTERS[str(root)] = copy.deepcopy(saved["active_pointer"])
    _RESTORED_ROOTS[str(root)] = (saved["generation"], {
        "generation": saved["generation"], "asset_count": len(saved["objects"]),
        "restored_count": 0, "active_run_id": (saved["active_pointer"] or {}).get("run_id"),
    })
    return saved


def _restore_entry(config, relative: str, entry: dict, objects: _AppStorageObjects) -> bool:
    root = config.root.resolve()
    destination = root / relative
    if not destination.resolve().is_relative_to(root) or not _is_library_asset(relative):
        raise DurableStorageError("The saved library inventory contains an unsafe path.")
    if destination.is_file() and not destination.is_symlink():
        if _sha256(destination) == (entry["sha256"], entry["size"]):
            return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=destination.parent) as temporary:
            candidate = Path(temporary) / destination.name
            objects.download(entry["object_key"], candidate)
            if _sha256(candidate) != (entry["sha256"], entry["size"]):
                raise DurableStorageError("A restored library asset failed its checksum.")
            os.replace(candidate, destination)
    except DurableStorageError:
        raise
    except Exception:
        raise DurableStorageError("App Storage could not restore a required library asset.") from None
    return True


def _validate_active(config, pointer: dict) -> None:
    if (pointer.get("status") != "verified" or not isinstance(pointer.get("run_id"), str)
            or not _HEX.fullmatch(pointer["run_id"])
            or not isinstance(pointer.get("xml_hash"), str)
            or not _HEX.fullmatch(pointer["xml_hash"])):
        raise DurableStorageError("The saved active library pointer failed validation.")
    try:
        from .indexing import manifest_records
        from .library_health import validate_local_run
        records = manifest_records(pointer, config)
        if pointer.get("full_library"):
            validate_local_run(config, pointer)
        else:
            from .xml_store import load_corpus
            xml_hash = pointer.get("xml_hash", "")
            path = config.path("corpus_dir") / xml_hash / "AmgenProducts.xml"
            corpus = load_corpus(path)
            if corpus.xml_hash != xml_hash:
                raise ValueError()
            by_id = {document.id: document for document in corpus.documents}
            for document_id in pointer.get("document_ids", []):
                document = by_id.get(document_id)
                if not document:
                    raise ValueError()
                pdf = path.parent / (document.sha256 + ".pdf")
                if _sha256(pdf)[0] != document.sha256:
                    raise ValueError()
            if not records:
                raise ValueError()
    except Exception:
        raise DurableStorageError(
            "The restored active library failed local citation or search-artifact validation."
        ) from None


def restore_from_app_storage(config, *, object_client=None, connect=_connect, state=None) -> dict:
    """Restore the authoritative inventory before application search is enabled."""
    state = state if state is not None else _read_state(connect=connect)
    if state is None:
        raise DurableStorageError(
            "No durable library manifest exists yet. Migrate the current library before starting hosted search."
        )
    storage = _AppStorageObjects(object_client)
    restored = 0
    for relative, entry in sorted(state["objects"].items()):
        restored += _restore_entry(config, relative, entry, storage)
    pointer = state["active_pointer"]
    if pointer is not None:
        _validate_active(config, pointer)
        from .service import atomic_json
        atomic_json(config.path("active_corpus_manifest"), pointer)
    result = {"generation": state["generation"], "asset_count": len(state["objects"]),
              "restored_count": restored, "active_run_id": (pointer or {}).get("run_id")}
    _RESTORED_ROOTS[str(config.root.resolve())] = (state["generation"], result)
    _ACTIVE_POINTERS[str(config.root.resolve())] = copy.deepcopy(pointer)
    return result


def seed_from_local(config, *, object_client=None, connect=_connect) -> dict:
    """One-time, non-destructive migration from intact local files to App Storage."""
    if _read_state(connect=connect) is not None:
        raise DurableStorageError("Persistent library storage is already initialized; refusing to overwrite it.")
    migrated_state = _migrate_sqlite_state(config, connect=connect)
    pointer_path = config.path("active_corpus_manifest")
    pointer = None
    if pointer_path.exists():
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise DurableStorageError("The local active library pointer cannot be migrated safely.") from None
        if not isinstance(pointer, dict):
            raise DurableStorageError("The local active library pointer cannot be migrated safely.")
        _validate_active(config, pointer)
    root = config.root.resolve()
    files = _asset_paths(root)
    storage = _AppStorageObjects(object_client)
    entries = {}
    for path in files:
        relative, entry = _entry_for(path, root, storage)
        entries[relative] = entry
    state = _commit_state(entries, pointer, initialize=True, connect=connect)
    result = {"generation": state["generation"], "asset_count": len(entries),
              "active_run_id": (pointer or {}).get("run_id"), **migrated_state}
    _RESTORED_ROOTS[str(config.root.resolve())] = (state["generation"], result)
    _ACTIVE_POINTERS[str(config.root.resolve())] = copy.deepcopy(pointer)
    return result


def restore_at_service_start(config) -> dict | None:
    if not backend_enabled():
        return None
    key = str(config.root.resolve())
    cached = _RESTORED_ROOTS.get(key)
    if cached is not None:
        return cached[1]
    return restore_from_app_storage(config)


def persist_active_library(config, pointer: dict) -> dict:
    """Publish all current cache assets first, then atomically advance SQL state."""
    if not backend_enabled():
        return {}
    return sync_paths(config, active=pointer)


def clear_restore_cache() -> None:
    """Clear process-local cache for tests and explicit integrity rechecks."""
    _RESTORED_ROOTS.clear()
    _ACTIVE_POINTERS.clear()
