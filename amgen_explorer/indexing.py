"""Resumable, explicitly published Documents API runs with local atomic manifests."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import fcntl
from .connectivity import DocumentsClient, ProviderError


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".candidate-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, ensure_ascii=False, sort_keys=True, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None


def guard_text(text):
    # Each byte can account for at most one byte-fallback token; reserve special
    # tokens. Conservative, not an assertion of exact model tokenization.
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Document/query text must be nonempty.")
    if len(text.encode("utf-8")) + 8 > 2048:
        raise ValueError("Text exceeds the conservative model token guard (UTF-8 bytes + 8 <= 2048). Split or narrow the text.")


def flat_metadata(metadata):
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a flat mapping.")
    for key, value in metadata.items():
        if not isinstance(key, str) or not key or key.startswith(("_", "$")) or len(key.encode()) > 64:
            raise ValueError("Metadata contains an invalid field name.")
        valid = type(value) in (str, bool, int) or (type(value) is float and math.isfinite(value))
        valid |= isinstance(value, list) and all(isinstance(x, str) for x in value)
        if not valid:
            raise ValueError("Metadata supports only finite flat scalar values or string lists.")
    if len(json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode()) > 40_000:
        raise ValueError("Metadata exceeds 40 KB.")


def index_profile(config):
    return {k: v for k, v in config.settings["pinecone"].items()
            if k not in {"batch_size", "max_batch_bytes"}}


def validate_manifest_records(manifest, records, config):
    """Verify content-addressed records, destination and scope before any use.

    The existing run ID already binds all records, plan and profile, so this
    check also protects pre-existing manifests without a format migration.
    """
    if not isinstance(manifest, dict) or manifest.get("profile") != index_profile(config):
        raise ValueError("Run targets an incompatible index or embedding profile.")
    run_id = manifest.get("run_id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{64}", run_id):
        raise ValueError("Invalid run identifier in records manifest.")
    expected_namespace = manifest["profile"]["namespace_prefix"] + "-" + run_id[:48]
    if manifest.get("namespace") != expected_namespace:
        raise ValueError("Run namespace does not match its pinned identity.")
    if not isinstance(records, list) or not records or len(records) != manifest.get("record_count"):
        raise ValueError("Staged records are missing or incomplete.")
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("Invalid staged record shape.")
    try:
        actual_run = digest({"plan": manifest["fingerprint"], "records": records, "profile": manifest["profile"]})
        ids = [r["_id"] for r in records]
        products = sorted({r["product_id"] for r in records})
        documents = sorted({r["document_id"] for r in records})
    except (KeyError, ValueError, TypeError):
        raise ValueError("Staged records failed integrity validation.") from None
    if actual_run != run_id or len(set(ids)) != len(ids):
        raise ValueError("Staged records failed content-hash or unique-ID validation.")
    if products != manifest.get("product_ids") or documents != manifest.get("document_ids"):
        raise ValueError("Run scope does not match the staged records.")
    for record in records:
        if (record.get("xml_hash") != manifest.get("xml_hash")
                or record.get("chunk_config_hash") != manifest.get("config_hash")
                or record.get("review_hash") != manifest.get("review_hash")
                or record.get("review_state") != "accepted"):
            raise ValueError("A staged record failed source/review/configuration pin validation.")
    # These duplicated display fields must not contradict the authoritative
    # profile; older manifests may omit them.
    for key in ("index_host", "index_name", "embedding_model", "api_version"):
        if key in manifest and manifest[key] != manifest["profile"][key]:
            raise ValueError("Run destination metadata contradicts its pinned profile.")


def manifest_records(manifest, config):
    run_id = manifest.get("run_id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{64}", run_id):
        raise ValueError("Invalid run identifier in records manifest.")
    name = manifest.get("records_path", "")
    if not isinstance(name, str) or not name:
        raise ValueError("Run has no immutable records path.")
    path = (config.root / name).resolve()
    expected_path = (config.path("manifest_dir") / (run_id + ".chunks.json")).resolve()
    if not path.is_relative_to(config.root) or path != expected_path:
        raise ValueError("Run records path does not match its pinned identity.")
    records = read_json(path)
    validate_manifest_records(manifest, records, config)
    return records


class IndexService:
    def __init__(self, config, client=None, *, sleep=time.sleep, verification_attempts=6):
        self.config = config
        self.client = client or DocumentsClient(config)
        self.sleep = sleep
        self.verification_attempts = verification_attempts

    def _profile(self):
        return index_profile(self.config)

    def _run_path(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{64}", run_id):
            raise ValueError("Invalid run identifier.")
        return self.config.path("manifest_dir") / (run_id + ".json")

    def _records(self, plan):
        records = []
        seen = set()
        for chunk in plan.chunks:
            guard_text(chunk.text)
            if not isinstance(chunk.id, str) or not chunk.id or len(chunk.id.encode()) > 512 or not chunk.id.isascii():
                raise ValueError("Chunk ID must be nonempty ASCII and at most 512 bytes.")
            if chunk.id in seen:
                raise ValueError("Duplicate chunk IDs are not allowed.")
            seen.add(chunk.id)
            metadata = dict(chunk.metadata)
            for field in ("product_id", "document_id", "document_sha256", "section_id", "page_start", "page_end"):
                if field not in metadata:
                    raise ValueError(f"Missing citation metadata: {field}.")
            if type(metadata["page_start"]) is not int or type(metadata["page_end"]) is not int or not 1 <= metadata["page_start"] <= metadata["page_end"]:
                raise ValueError("Citation pages must be valid 1-based PDF page bounds.")
            if metadata.get("review_state") != "accepted":
                raise ValueError("Only explicitly accepted reviewed chunks can be loaded.")
            metadata.update(xml_hash=plan.xml_hash, chunk_config_hash=plan.config_hash, review_hash=plan.review_hash)
            if self.config.settings["pinecone"]["text_field"] in metadata:
                raise ValueError("Metadata cannot overwrite document text.")
            flat_metadata(metadata)
            records.append({**metadata, "_id": chunk.id, self.config.settings["pinecone"]["text_field"]: chunk.text})
        return records

    def _batches(self, records):
        pc = self.config.settings["pinecone"]
        current = []
        for record in records:
            candidate = current + [record]
            if len(json.dumps({"documents": candidate}, ensure_ascii=False).encode()) > pc["max_batch_bytes"] or len(candidate) > min(96, pc["batch_size"]):
                if not current:
                    raise ValueError("A record exceeds the configured upload batch byte limit.")
                yield current
                current = [record]
                if len(json.dumps({"documents": current}, ensure_ascii=False).encode()) > pc["max_batch_bytes"]:
                    raise ValueError("A record exceeds the configured upload batch byte limit.")
            else:
                current = candidate
        if current:
            yield current

    def preview(self, plan):
        errors = self.config.validate()
        if errors:
            raise ValueError(" ".join(errors))
        records = self._records(plan)
        profile = self._profile()
        run_id = digest({"plan": plan.fingerprint, "records": records, "profile": profile})
        batches = list(self._batches(records))
        return {"run_id": run_id, "namespace": self.config.settings["pinecone"]["namespace_prefix"] + "-" + run_id[:48],
                "fingerprint": plan.fingerprint, "xml_hash": plan.xml_hash, "config_hash": plan.config_hash,
                "review_hash": plan.review_hash, "record_count": len(records), "excluded_count": len(plan.excluded),
                "estimated_tokens": sum(c.token_count for c in plan.chunks), "batch_count": len(batches),
                "product_ids": sorted({r["product_id"] for r in records}),
                "document_ids": sorted({r["document_id"] for r in records}), "profile": profile,
                "index_host": profile["index_host"], "index_name": profile["index_name"],
                "embedding_model": profile["embedding_model"], "api_version": profile["api_version"],
                "token_guard": "conservative UTF-8 bytes + 8 <= 2048; not exact tokenizer"}

    @contextmanager
    def _lock(self):
        database = self.config.path("ingestion_database")
        database.parent.mkdir(parents=True, exist_ok=True)
        # Kernel lock releases on crash; SQLite retains job and batch checkpoints.
        with open(str(database) + ".lock", "a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another indexing or publication job is running. Retry after it finishes.") from None
            db = sqlite3.connect(database)
            try:
                db.execute("CREATE TABLE IF NOT EXISTS batches (run TEXT, batch TEXT, attempts INTEGER DEFAULT 0, done INTEGER DEFAULT 0, PRIMARY KEY(run,batch))")
                db.execute("CREATE TABLE IF NOT EXISTS job_lock (target TEXT PRIMARY KEY, pid INTEGER, started REAL)")
                db.execute("INSERT OR REPLACE INTO job_lock VALUES (?,?,?)", (digest(self._profile()), os.getpid(), time.time()))
                db.commit()
                yield db
            finally:
                db.execute("DELETE FROM job_lock WHERE pid=?", (os.getpid(),))
                db.commit()
                db.close()
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _verify(self, manifest, records):
        ns = manifest["namespace"]
        field = self.config.settings["pinecone"]["text_field"]
        for attempt in range(self.verification_attempts):
            complete = True
            for start in range(0, len(records), 96):
                expected = records[start:start + 96]
                actual = self.client.fetch(ns, [r["_id"] for r in expected])
                for record in expected:
                    received = actual.get(record["_id"], {})
                    if any(received.get(k) != v for k, v in record.items()):
                        complete = False
            if complete:
                # Check search visibility independently for every document scope.
                for document_id in manifest["document_ids"]:
                    record = next(r for r in records if r["document_id"] == document_id)
                    filters = {"$and": [{"document_id": {"$eq": document_id}}, {"product_id": {"$eq": record["product_id"]}}, {"xml_hash": {"$eq": manifest["xml_hash"]}}]}
                    hits = self.client.search(ns, record[field][:200], filters, 5)
                    expected_ids = {r["_id"] for r in records if r["document_id"] == document_id}
                    if not any(h.get("_id") in expected_ids for h in hits):
                        complete = False
                        break
            if complete:
                return
            if attempt + 1 < self.verification_attempts:
                self.sleep(min(2 ** attempt, 8))
        raise ValueError("Staged records are not fully fetchable and searchable yet. Retry Load; the active corpus was preserved.")

    def ingest(self, plan, on_progress=None):
        manifest = self.preview(plan)
        if not plan.chunks:
            raise ValueError("No reviewed, eligible chunks are available to load.")
        records = self._records(plan)
        report = on_progress or (lambda value: None)
        with self._lock() as db:
            self.client.check()  # schema/model/host validation always precedes writes
            old = read_json(self._run_path(manifest["run_id"]))
            if old is not None and (not isinstance(old, dict) or old.get("run_id") != manifest["run_id"]):
                raise ValueError("Saved run manifest does not match its requested identity.")
            if old and old.get("status") == "verified":
                manifest_records(old, self.config)
                return old
            manifest.update(status="indexing", created_at=(old or {}).get("created_at", time.time()), succeeded=0, failed_ids=[],
                            usage=(old or {}).get("usage", {"embed_total_tokens": 0}),
                            usage_may_include_unreported_retries=(old or {}).get("usage_may_include_unreported_retries", False))
            record_path = self._run_path(manifest["run_id"]).with_suffix(".chunks.json")
            manifest["records_path"] = str(record_path.relative_to(self.config.root))
            atomic_json(record_path, records)
            atomic_json(self._run_path(manifest["run_id"]), manifest)
            try:
                for batch in self._batches(records):
                    batch_id = digest(batch)
                    state = db.execute("SELECT done FROM batches WHERE run=? AND batch=?", (manifest["run_id"], batch_id)).fetchone()
                    if not state or not state[0]:
                        db.execute("INSERT OR IGNORE INTO batches(run,batch) VALUES (?,?)", (manifest["run_id"], batch_id))
                        db.commit()
                        for attempt in range(4):
                            db.execute("UPDATE batches SET attempts=attempts+1 WHERE run=? AND batch=?", (manifest["run_id"], batch_id))
                            db.commit()
                            try:
                                response = self.client.upsert(manifest["namespace"], batch)
                                if response.get("upserted_count") != len(batch):
                                    raise ValueError("Provider did not confirm the complete batch.")
                                manifest["usage"]["embed_total_tokens"] += response.get("usage", {}).get("embed_total_tokens", 0)
                                break
                            except ProviderError as exc:
                                manifest["usage_may_include_unreported_retries"] = True
                                if not exc.retryable or attempt == 3:
                                    raise
                                self.sleep(min(.25 * 2 ** attempt, 2))
                        db.execute("UPDATE batches SET done=1 WHERE run=? AND batch=?", (manifest["run_id"], batch_id))
                        db.commit()
                    manifest["succeeded"] += len(batch)
                    atomic_json(self._run_path(manifest["run_id"]), manifest)
                    report(dict(manifest))
                manifest["status"] = "verifying"
                atomic_json(self._run_path(manifest["run_id"]), manifest)
                report(dict(manifest))
                self._verify(manifest, records)
                manifest.update(status="verified", verified_at=time.time())
            except Exception:
                manifest.update(status="failed", failed_ids=[r["_id"] for r in records][manifest["succeeded"]:],
                                error="Load or verification failed. Check configuration/connectivity and retry this unchanged plan.")
                atomic_json(self._run_path(manifest["run_id"]), manifest)
                report(dict(manifest))
                raise
            atomic_json(self._run_path(manifest["run_id"]), manifest)
            report(dict(manifest))
            return manifest

    def active(self):
        return read_json(self.config.path("active_corpus_manifest"))

    def runs(self):
        folder = self.config.path("manifest_dir")
        if not folder.exists():
            return []
        return sorted([read_json(p) for p in folder.glob("*.json") if re.fullmatch(r"[a-f0-9]{64}\.json", p.name)],
                      key=lambda r: r.get("created_at", 0), reverse=True)

    def activate(self, run_id, current_plan=None):
        if current_plan is None:
            raise ValueError("Publication requires the current reviewed chunk plan to detect stale previews.")
        if self.preview(current_plan)["run_id"] != run_id:
            raise ValueError("Sources, review, chunk settings or index profile changed. Preview and load again.")
        return self._publish(run_id)

    def _publish(self, run_id):
        with self._lock():
            manifest = read_json(self._run_path(run_id))
            if manifest is not None and (not isinstance(manifest, dict) or manifest.get("run_id") != run_id):
                raise ValueError("Saved run manifest does not match its requested identity.")
            if not manifest or manifest.get("status") != "verified":
                raise ValueError("Only a complete, verified run can be published.")
            records = manifest_records(manifest, self.config)
            self.client.check()
            self._verify(manifest, records)
            previous = self.active()
            active = {**manifest, "published_at": time.time(), "previous_run_id": (previous or {}).get("run_id")}
            atomic_json(self.config.path("active_corpus_manifest"), active)
            return active

    def rollback(self, run_id):
        return self._publish(run_id)
