"""Application orchestration shared by Streamlit and integration scripts.

Constructing this service never calls a provider. Cloud writes occur only through
load/publish; corpus generation and review stay on the local machine.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from amgen_explorer.config import load_config
from amgen_explorer.models import Corpus, TeachingResponse


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@lru_cache(maxsize=4)
def _read_corpus(path: str, mtime_ns: int, size: int) -> Corpus:
    from amgen_explorer.xml_store import load_corpus
    return load_corpus(Path(path))


class ExplorerService:
    def __init__(self, config=None):
        self.config = config or load_config()
        errors = self.config.validate()
        if errors:
            raise ValueError(" ".join(errors))

    @property
    def reviews(self):
        from amgen_explorer.review import ReviewStore
        return ReviewStore(self.config.path("review_database"))

    @property
    def index(self):
        from amgen_explorer.indexing import IndexService
        return IndexService(self.config)

    def corpus(self):
        path = self.config.path("xml_output")
        if not path.exists():
            return None
        stat = path.stat()
        return _read_corpus(str(path), stat.st_mtime_ns, stat.st_size)

    def inventory(self):
        directory = self.config.path("source_dir")
        if not directory.exists():
            return []
        return [{"filename": path.name, "bytes": path.stat().st_size,
                 "size_mb": round(path.stat().st_size / 1_048_576, 2), "type": "PDF"}
                for path in sorted(directory.iterdir()) if path.is_file() and path.suffix.lower() == ".pdf"]

    def build(self):
        from amgen_explorer.extraction import build_corpus
        report = build_corpus(self.config.path("source_dir"), self.config.path("xml_output"))
        _read_corpus.cache_clear()
        return report

    def connection_status(self):
        from amgen_explorer.connectivity import check_connections
        return check_connections(self.config)

    def chunk_config(self, target_tokens=600, overlap_tokens=80):
        from amgen_explorer.chunking import ChunkConfig
        return ChunkConfig(target_tokens=target_tokens, overlap_tokens=overlap_tokens,
                           prefix_template=self.config.settings["chunking"]["prefix_template"])

    def preview(self, chunk_config, product_id=None, document_id=None):
        from amgen_explorer.chunking import prepare_chunks
        corpus = self.corpus()
        if corpus is None:
            raise ValueError("Build the consolidated XML before previewing chunks.")
        selected = replace(corpus, blocks=[b for b in corpus.blocks
            if (not product_id or b.product_id == product_id)
            and (not document_id or b.document_id == document_id)])
        plan = prepare_chunks(selected, self.reviews, chunk_config)
        plan.settings["selection"] = {"product_id": product_id, "document_id": document_id}
        return plan

    def review(self, block_id, decision, reviewer, note=""):
        corpus = self.corpus()
        if corpus is None:
            raise ValueError("Build XML before recording a review.")
        block = next((b for b in corpus.blocks if b.id == block_id), None)
        if block is None:
            raise ValueError("Passage no longer exists; refresh the source preview.")
        self._verified_document(block.document_id, corpus)
        self.reviews.record(block, decision, reviewer, note)

    def _fresh_plan(self, plan):
        from amgen_explorer.chunking import ChunkConfig
        settings = dict(plan.settings)
        selection = settings.pop("selection", {})
        # Only user controls are reloaded; implementation/tokenizer versions are
        # resolved by ChunkConfig, so an upgrade invalidates an old preview.
        controls = {k: settings[k] for k in ("target_tokens", "overlap_tokens", "prefix_template") if k in settings}
        fresh = self.preview(ChunkConfig(**controls), **selection)
        if fresh.fingerprint != plan.fingerprint:
            raise ValueError("Sources, reviews or chunk settings changed. Preview the load again.")
        corpus = self.corpus()
        for doc_id in {c.metadata["document_id"] for c in fresh.chunks}:
            self._verified_document(doc_id, corpus)
        return fresh

    def load(self, plan, on_progress=None):
        fresh = self._fresh_plan(plan)
        self._snapshot(fresh)
        return self.index.ingest(fresh, on_progress=on_progress)

    def publish(self, run_id, plan):
        return self.index.activate(run_id, current_plan=self._fresh_plan(plan))

    def active(self):
        return self.index.active()

    def rollback(self, run_id):
        return self.index.rollback(run_id)

    def _snapshot(self, plan):
        corpus = self.corpus()
        folder = self.config.path("corpus_dir") / corpus.xml_hash
        folder.mkdir(parents=True, exist_ok=True)
        self._immutable_bytes(folder / "AmgenProducts.xml", corpus.xml_path.read_bytes())
        for doc_id in {c.metadata["document_id"] for c in plan.chunks}:
            doc, path = self._verified_document(doc_id, corpus)
            self._immutable_bytes(folder / (doc.sha256 + ".pdf"), path.read_bytes())

    @staticmethod
    def _immutable_bytes(path, payload):
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("A pinned source snapshot failed its integrity check.")
            return
        fd, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def _pinned_corpus(self, xml_hash):
        if not re.fullmatch(r"[a-f0-9]{64}", xml_hash or ""):
            raise ValueError("Invalid published XML identity.")
        path = self.config.path("corpus_dir") / xml_hash / "AmgenProducts.xml"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != xml_hash:
            raise ValueError("The published XML snapshot is unavailable or changed.")
        stat = path.stat()
        return _read_corpus(str(path), stat.st_mtime_ns, stat.st_size)

    def _verified_document(self, document_id, corpus=None, xml_hash=None):
        corpus = corpus or self.corpus()
        doc = next((d for d in corpus.documents if d.id == document_id), None) if corpus else None
        if not doc:
            raise ValueError("The cited document is not in the local corpus.")
        directory = (self.config.path("corpus_dir") / xml_hash) if xml_hash else self.config.path("source_dir")
        filename = (doc.sha256 + ".pdf") if xml_hash else Path(doc.filename).name
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError("The original source PDF is unavailable.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc.sha256:
            raise ValueError("The source PDF changed. Rebuild XML and review the new passages.")
        return doc, path

    def source_pdf(self, document_id, xml_hash=None):
        corpus = self._pinned_corpus(xml_hash) if xml_hash else None
        _, path = self._verified_document(document_id, corpus, xml_hash)
        return path.read_bytes()

    def source_page(self, document_id, page, xml_hash=None):
        import fitz
        corpus = self._pinned_corpus(xml_hash) if xml_hash else None
        doc, path = self._verified_document(document_id, corpus, xml_hash)
        if not isinstance(page, int) or not 1 <= page <= doc.page_count:
            raise ValueError("The PDF page number is out of range.")
        with fitz.open(path) as pdf:
            return pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).tobytes("png")

    def _evidence(self, question, product_id, document_id=None):
        from amgen_explorer.retrieval import retrieve
        active = self.active()
        if not active:
            return None
        corpus = self._pinned_corpus(active.get("xml_hash"))
        for document in corpus.documents:
            if document.product_id == product_id and (not document_id or document.id == document_id):
                if document.id in active.get("document_ids", []):
                    self._verified_document(document.id, corpus, active["xml_hash"])
        evidence = retrieve(question, product_id, active, self.config, document_id=document_id)
        # Revoked reviews must immediately stop their passages from being used.
        blocks = {b.id: b for b in corpus.blocks}
        for passage in evidence.passages:
            meta = passage.get("metadata", passage)
            block_ids = meta.get("block_ids", [])
            if isinstance(block_ids, str):
                try: block_ids = json.loads(block_ids)
                except ValueError: block_ids = [block_ids]
            if not block_ids or any(i not in blocks or self.reviews.status(blocks[i]) != "accepted" for i in block_ids):
                raise ValueError("A retrieved passage needs review. Publish an updated corpus before using it.")
        return evidence

    def answer(self, question, product_id, mode="Plain language", document_id=None, history=None):
        from amgen_explorer.teaching import teach
        evidence = self._evidence(question, product_id, document_id)
        if evidence is None:
            return TeachingResponse("This medicine has no published learning corpus yet. Open Manage sources to review passages, load Pinecone and publish them.", abstained=True)
        response = teach(question, evidence, self.config, mode=mode, history=history)
        response.evidence = evidence
        return response

    def reexplain(self, question, prior_response, mode, product_id, document_id=None):
        """Change reading depth using exactly the prior answer's evidence."""
        from amgen_explorer.teaching import teach
        evidence = prior_response.evidence
        if evidence is None or prior_response.abstained or evidence.question != question or evidence.product_id != product_id:
            raise ValueError("Choose a supported answer from this medicine to change its explanation style.")
        corpus = self._pinned_corpus(evidence.xml_hash)
        blocks = {b.id: b for b in corpus.blocks}
        for passage in evidence.passages:
            metadata = passage["metadata"]
            if document_id and metadata["document_id"] != document_id:
                raise ValueError("This answer belongs to a different source scope.")
            self._verified_document(metadata["document_id"], corpus, evidence.xml_hash)
            if any(i not in blocks or self.reviews.status(blocks[i]) != "accepted" for i in metadata["block_ids"]):
                raise ValueError("A supporting passage needs review before it can be explained again.")
        response = teach(question, evidence, self.config, mode=mode)
        response.evidence = evidence
        return response

    def quiz(self, product_id, document_id=None):
        from amgen_explorer.teaching import make_quiz
        evidence = self._evidence("How does this medicine work? Explain its mechanism of action.", product_id, document_id)
        if evidence is None or not evidence.passages:
            return {"error": "Publish reviewed mechanism passages before starting a knowledge check."}
        return make_quiz(evidence, self.config)

    def presets(self):
        path = self.config.root / "data/chunk-presets.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            raise ValueError("Saved chunk configurations cannot be read.") from None
        return data if isinstance(data, dict) else {}

    def save_preset(self, name, chunk_config):
        name = name.strip()
        if not re.fullmatch(r"[\w .-]{1,60}", name):
            raise ValueError("Use 1–60 letters, numbers, spaces, dots or hyphens for a preset name.")
        data = self.presets()
        data[name] = {"settings": chunk_config.as_dict(), "config_hash": chunk_config.fingerprint()}
        atomic_json(self.config.root / "data/chunk-presets.json", data)

    def compare(self, run_a, run_b, questions, product_id):
        from amgen_explorer.retrieval import retrieve
        runs = {r["run_id"]: r for r in self.index.runs()}
        if run_a == run_b or run_a not in runs or run_b not in runs:
            raise ValueError("Choose two different verified test builds.")
        a, b = runs[run_a], runs[run_b]
        if a.get("status") != "verified" or b.get("status") != "verified":
            raise ValueError("Both builds must pass verification before comparison.")
        for key in ("xml_hash", "review_hash", "profile"):
            if a.get(key) != b.get(key):
                raise ValueError("Compare builds with identical XML, review snapshot and embedding profile.")
        if not questions or not 1 <= len(questions) <= 20:
            raise ValueError("Provide 1–20 identical questions for both configurations.")
        rows = []
        for question in questions:
            row = {"question": question}
            for label, run in (("A", a), ("B", b)):
                start = time.monotonic()
                evidence = retrieve(question, product_id, run, self.config)
                coverage = set()
                for p in evidence.passages:
                    m = p.get("metadata", p)
                    for block in m.get("block_ids", []):
                        coverage.add((m.get("document_sha256"), block))
                row[label] = {"namespace": run["namespace"], "seconds": round(time.monotonic() - start, 3),
                              "passages": evidence.passages, "source_blocks": len(coverage), "warnings": evidence.warnings}
            rows.append(row)
        return {"xml_hash": a["xml_hash"], "product_id": product_id, "rows": rows,
                "evidence_token_budget": self.config.settings["retrieval"]["evidence_token_budget"],
                "note": "Same questions, product and evidence budget. Inspect source coverage and qualifiers; these are retrieval observations, not clinical accuracy scores."}
