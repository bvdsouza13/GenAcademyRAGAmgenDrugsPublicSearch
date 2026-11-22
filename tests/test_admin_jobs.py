"""Hosted Admin jobs remain claimable after a worker loses its lease."""
import copy
import json
from contextlib import nullcontext

import pytest

from amgen_explorer import admin_jobs


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class JobDatabase:
    def __init__(self):
        self.rows = {}

    def connect(self):
        return JobConnection(self)


class JobConnection:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=None):
        normalized = " ".join(query.casefold().split())
        if normalized.startswith("select job_id from amgen_admin_jobs"):
            row = next((item for item in self.database.rows.values()
                        if item["status"] in {"queued", "running"}), None)
            return Result((row["job_id"],) if row else None)
        if normalized.startswith("insert into amgen_admin_jobs"):
            job_id, payload, progress = params
            if any(item["status"] in {"queued", "running"}
                   for item in self.database.rows.values()):
                raise RuntimeError("active job unique constraint")
            self.database.rows[job_id] = {
                "job_id": job_id, "kind": "build_library", "status": "queued",
                "payload": json.loads(payload), "progress": json.loads(progress),
                "result": None, "error": None, "attempts": 0, "lease_age": 0,
            }
            return Result()
        if normalized.startswith("with candidate as"):
            age, worker_id = params
            row = next((item for item in self.database.rows.values()
                        if item["status"] == "queued"
                        or (item["status"] == "running" and item["lease_age"] > age)), None)
            if not row:
                return Result()
            row.update(status="running", worker_id=worker_id, attempts=row["attempts"] + 1,
                       lease_age=0)
            return Result((row["job_id"], row["kind"], copy.deepcopy(row["payload"])))
        if normalized.startswith("select job_id, kind, status, progress, result, error, attempts, updated_at"):
            row = next(reversed(self.database.rows.values()), None)
            if "where job_id = %s" in normalized:
                row = self.database.rows.get(params[0])
            if not row:
                return Result()
            return Result(tuple(row.get(key) for key in (
                "job_id", "kind", "status", "progress", "result", "error", "attempts"
            )) + (None,))
        if normalized.startswith("update amgen_admin_jobs set"):
            status, progress, result, error, _end_status, job_id, worker_id = params
            row = self.database.rows[job_id]
            if row.get("worker_id") == worker_id and row["status"] == "running":
                if status:
                    row["status"] = status
                    if status in {"completed", "failed"}:
                        row["worker_id"] = None
                if progress:
                    row["progress"] = json.loads(progress)
                if result:
                    row["result"] = json.loads(result)
                if error:
                    row["error"] = error
            return Result()
        if normalized.startswith("update amgen_admin_jobs set heartbeat_at"):
            return Result()
        raise AssertionError(f"Unexpected SQL: {query}")


def test_interrupted_running_job_is_reclaimed_after_its_lease_expires(monkeypatch):
    database = JobDatabase()
    monkeypatch.setattr("amgen_explorer.durable_library.database_connection", database.connect)
    queued = admin_jobs.enqueue_build({"chunk_settings": {"target_tokens": 600}})

    first = admin_jobs._claim("worker-one")
    assert first["job_id"] == queued["job_id"]
    row = database.rows[queued["job_id"]]
    assert row["status"] == "running" and row["attempts"] == 1

    # A restarted worker can take over only after the original worker's lease expires.
    row["lease_age"] = admin_jobs._LEASE_SECONDS + 1
    recovered = admin_jobs._claim("worker-two")
    assert recovered == first
    assert row["worker_id"] == "worker-two" and row["attempts"] == 2


def test_only_one_hosted_build_can_be_queued_or_running(monkeypatch):
    database = JobDatabase()
    monkeypatch.setattr("amgen_explorer.durable_library.database_connection", database.connect)
    admin_jobs.enqueue_build({"chunk_settings": {"target_tokens": 600}})
    with pytest.raises(admin_jobs.AdminJobError, match="already queued or running"):
        admin_jobs.enqueue_build({"chunk_settings": {"target_tokens": 800}})


def test_job_status_is_persisted_and_readable_after_worker_restart(monkeypatch):
    database = JobDatabase()
    monkeypatch.setattr("amgen_explorer.durable_library.database_connection", database.connect)
    queued = admin_jobs.enqueue_build({"chunk_settings": {"target_tokens": 600}})
    admin_jobs._claim("worker-one")
    row = database.rows[queued["job_id"]]
    row.update(status="completed", result={"run_id": "a" * 64},
               progress={"stage": "Ready", "succeeded": 12, "record_count": 12})

    saved = admin_jobs.get_job()
    assert saved["job_id"] == queued["job_id"]
    assert saved["status"] == "completed"
    assert saved["result"]["run_id"] == "a" * 64
    assert saved["progress"]["succeeded"] == 12
