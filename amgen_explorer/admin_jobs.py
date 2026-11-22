"""Durable hosted Admin jobs backed by the managed SQL database."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid


_WORKER_LOCK = threading.Lock()
_WORKERS: dict[str, threading.Thread] = {}
_LEASE_SECONDS = 90
_POLL_SECONDS = 2


class AdminJobError(RuntimeError):
    """A sanitized durable Admin-job persistence or coordination failure."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def enqueue_build(settings: dict) -> dict:
    """Persist a build request before acknowledging it to the browser."""
    from .durable_library import database_connection

    job_id = uuid.uuid4().hex
    try:
        with database_connection() as connection:
            with connection.transaction():
                running = connection.execute(
                    "SELECT job_id FROM amgen_admin_jobs "
                    "WHERE status IN ('queued', 'running') FOR UPDATE"
                ).fetchone()
                if running:
                    raise AdminJobError("A library build is already queued or running.")
                connection.execute(
                    "INSERT INTO amgen_admin_jobs "
                    "(job_id, kind, status, payload, progress, created_at, updated_at) "
                    "VALUES (%s, 'build_library', 'queued', %s::jsonb, %s::jsonb, now(), now())",
                    (job_id, _json(settings), _json({"stage": "Queued", "succeeded": 0, "record_count": 0})),
                )
    except AdminJobError:
        raise
    except Exception:
        raise AdminJobError("Unable to queue a durable library build. Check managed Admin-job storage.") from None
    return {"job_id": job_id, "kind": "build_library", "status": "queued"}


def get_job(job_id: str | None = None) -> dict | None:
    from .durable_library import database_connection

    try:
        with database_connection() as connection:
            if job_id:
                row = connection.execute(
                    "SELECT job_id, kind, status, progress, result, error, attempts, updated_at "
                    "FROM amgen_admin_jobs WHERE job_id = %s", (job_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT job_id, kind, status, progress, result, error, attempts, updated_at "
                    "FROM amgen_admin_jobs ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
    except Exception:
        raise AdminJobError("Unable to read durable Admin-job status.") from None
    if not row:
        return None
    keys = ("job_id", "kind", "status", "progress", "result", "error", "attempts", "updated_at")
    result = dict(zip(keys, row))
    for key in ("progress", "result"):
        value = result[key]
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except ValueError:
                raise AdminJobError("Saved Admin-job status failed validation.") from None
    return result


def _claim(worker_id: str) -> dict | None:
    from .durable_library import database_connection

    with database_connection() as connection:
        with connection.transaction():
            row = connection.execute(
                "WITH candidate AS ("
                " SELECT job_id FROM amgen_admin_jobs"
                " WHERE status = 'queued' OR (status = 'running' AND heartbeat_at < "
                "       now() - (%s * interval '1 second'))"
                " ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                ") UPDATE amgen_admin_jobs AS jobs"
                " SET status = 'running', worker_id = %s, heartbeat_at = now(),"
                "     updated_at = now(), attempts = attempts + 1"
                " FROM candidate WHERE jobs.job_id = candidate.job_id"
                " RETURNING jobs.job_id, jobs.kind, jobs.payload",
                (_LEASE_SECONDS, worker_id),
            ).fetchone()
    if not row:
        return None
    payload = row[2]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            _fail(row[0], worker_id, "The saved Admin job failed validation.")
            return None
    if row[1] != "build_library" or not isinstance(payload, dict):
        _fail(row[0], worker_id, "The saved Admin job is not supported.")
        return None
    return {"job_id": row[0], "kind": row[1], "payload": payload}


def _update(job_id: str, worker_id: str, *, status=None, progress=None, result=None, error=None):
    from .durable_library import database_connection

    try:
        with database_connection() as connection:
            connection.execute(
                "UPDATE amgen_admin_jobs SET "
                "status = COALESCE(%s, status), "
                "progress = COALESCE(%s::jsonb, progress), "
                "result = COALESCE(%s::jsonb, result), "
                "error = COALESCE(%s, error), "
                "heartbeat_at = now(), updated_at = now(), "
                "worker_id = CASE WHEN %s IN ('completed', 'failed') THEN NULL ELSE worker_id END "
                "WHERE job_id = %s AND worker_id = %s AND status = 'running'",
                (status, _json(progress) if progress is not None else None,
                 _json(result) if result is not None else None, error, status, job_id, worker_id),
            )
    except Exception:
        raise AdminJobError("Unable to save durable Admin-job progress.") from None


def _fail(job_id: str, worker_id: str, message: str):
    try:
        _update(job_id, worker_id, status="failed", error=message)
    except AdminJobError:
        pass


def _heartbeat(job_id: str, worker_id: str, stopped: threading.Event):
    from .durable_library import database_connection

    while not stopped.wait(10):
        try:
            with database_connection() as connection:
                connection.execute(
                    "UPDATE amgen_admin_jobs SET heartbeat_at = now(), updated_at = now() "
                    "WHERE job_id = %s AND worker_id = %s AND status = 'running'",
                    (job_id, worker_id),
                )
        except Exception:
            # The lease can expire and another process can safely resume from
            # persisted ingestion checkpoints if SQL remains unavailable.
            return


def _execute(config, job: dict, worker_id: str):
    from .chunking import ChunkConfig
    from .service import ExplorerService

    service = ExplorerService(config=config, _start_admin_worker=False)
    stopped = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat, args=(job["job_id"], worker_id, stopped),
        name="amgen-admin-job-heartbeat", daemon=True,
    )
    heartbeat.start()
    try:
        chunk_config = ChunkConfig(**job["payload"]["chunk_settings"])

        def progress(report):
            _update(job["job_id"], worker_id, progress={
                "stage": str(report.get("stage") or report.get("status") or "Working"),
                "succeeded": int(report.get("succeeded", report.get("processed", 0)) or 0),
                "record_count": int(report.get("record_count", report.get("records", 0)) or 0),
            })

        from .library import build_library
        result = build_library(service, chunk_config, activate=True, on_progress=progress)
        _update(job["job_id"], worker_id, status="completed", progress={
            "stage": "Ready", "succeeded": result.get("record_count", 0),
            "record_count": result.get("record_count", 0),
        }, result={key: result.get(key) for key in (
            "run_id", "status", "record_count", "document_count", "product_count", "published_at"
        )})
    except BaseException:
        _fail(job["job_id"], worker_id,
              "Build did not complete verification. The previously active library was preserved; retry from Admin.")
    finally:
        stopped.set()
        heartbeat.join(timeout=1)


def _worker(config, worker_id: str):
    while True:
        try:
            job = _claim(worker_id)
            if job:
                _execute(config, job, worker_id)
            else:
                time.sleep(_POLL_SECONDS)
        except Exception:
            time.sleep(_POLL_SECONDS)


def start_worker(config):
    """Start at most one process-local queue consumer; SQL coordinates replicas."""
    key = str(config.root.resolve())
    with _WORKER_LOCK:
        current = _WORKERS.get(key)
        if current and current.is_alive():
            return
        worker_id = f"{os.getpid()}-{uuid.uuid4().hex}"
        thread = threading.Thread(
            target=_worker, args=(config, worker_id),
            name="amgen-admin-job-worker", daemon=True,
        )
        _WORKERS[key] = thread
        thread.start()
