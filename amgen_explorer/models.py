"""Shared, provider-independent contracts for the local learning application."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class Product:
    id: str
    name: str
    generic_name: str = ""
    document_ids: list[str] = field(default_factory=list)

@dataclass
class Document:
    id: str
    product_id: str
    filename: str
    sha256: str
    page_count: int
    revision: str = ""
    variant_hint: str = ""

@dataclass
class SourceBlock:
    id: str
    product_id: str
    document_id: str
    document_sha256: str
    text: str
    section_id: str
    section_title: str
    section_kind: str
    page_start: int
    page_end: int
    content_hash: str
    spans: list[dict[str, Any]] = field(default_factory=list)
    parser_version: str = "1"
    warnings: list[str] = field(default_factory=list)

@dataclass
class Corpus:
    xml_path: Path
    xml_hash: str
    products: list[Product]
    documents: list[Document]
    blocks: list[SourceBlock]
    warnings: list[str] = field(default_factory=list)

@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]
    token_count: int

@dataclass
class ChunkPlan:
    chunks: list[Chunk]
    excluded: list[dict[str, Any]]
    fingerprint: str
    xml_hash: str
    config_hash: str
    review_hash: str
    settings: dict[str, Any] = field(default_factory=dict)

@dataclass
class EvidenceBundle:
    question: str
    product_id: str
    namespace: str
    xml_hash: str
    passages: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

@dataclass
class TeachingResponse:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    abstained: bool = False
    followups: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    evidence: EvidenceBundle | None = None

@dataclass
class BuildReport:
    output_path: str
    xml_hash: str
    product_count: int
    document_count: int
    page_count: int
    block_count: int
    schema_valid: bool
    warnings: list[str] = field(default_factory=list)
    input_count: int = 0
    failed_files: list[dict[str, Any]] = field(default_factory=list)
    failed_pages: list[dict[str, Any]] = field(default_factory=list)
    schema_status: str = "notValidated"
    snapshot_path: str = ""
