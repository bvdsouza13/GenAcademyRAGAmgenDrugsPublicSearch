#!/usr/bin/env python3
"""Build a local, unreviewed PI text corpus; no network, LLM, or vector writes.

Requires PyMuPDF 1.26.7. Run from any directory:
    .venv-corpus/bin/python scripts/build_amgen_xml.py
    .venv-corpus/bin/python scripts/build_amgen_xml.py --validate-only

The supplied template is a custom model, not FDA SPL. Local structural XSD
validation is separate from evidence verification and clinical review.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import asdict
from .models import BuildReport
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import pymupdf

NS = "urn:local:pi-corpus:1"
EXT = "urn:local:pi-corpus:extraction:1"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
ET.register_namespace("", NS)
ET.register_namespace("corpus", EXT)
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
PREFIX = {"p": NS, "c": EXT}
HEADINGS = {
    1: ["INDICATIONS AND USAGE"],
    2: ["DOSAGE AND ADMINISTRATION"],
    3: ["DOSAGE FORMS AND STRENGTHS"],
    4: ["CONTRAINDICATIONS"],
    5: ["WARNINGS AND PRECAUTIONS"],
    6: ["ADVERSE REACTIONS"],
    7: ["DRUG INTERACTIONS"],
    8: ["USE IN SPECIFIC POPULATIONS"],
    9: ["DRUG ABUSE AND DEPENDENCE"],
    10: ["OVERDOSAGE"],
    11: ["DESCRIPTION"],
    12: ["CLINICAL PHARMACOLOGY"],
    13: ["NONCLINICAL TOXICOLOGY"],
    14: ["CLINICAL STUDIES", "CLINICAL TRIALS"],
    15: ["REFERENCES"],
    16: ["HOW SUPPLIED/STORAGE AND HANDLING"],
    17: ["PATIENT COUNSELING INFORMATION"],
}
COMMON_WARNINGS = [
    "Machine extraction is unreviewed; structured clinical fields remain unknown.",
    "Text-layer coverage does not establish visual completeness. Figures, table-cell relationships, superscripts, and reading order require source-PDF review; no OCR was performed.",
    "Source content-stream order is retained (sort=False); geometric sorting can interleave two-column Highlights.",
    "Source-page archive and candidate section fragments intentionally overlap. Do not index both as independent evidence; deduplicate by document, page, and character offsets.",
    "Candidate sections and subsections are detected after the full-PI heading, excluding the contents list. Boxed warnings, tables and patient-labeling boundaries are not clinically validated.",
    "Local source files were supplied. Original download URLs, HTTP metadata, retrieval times, current-label status, and supersession relationships are unknown.",
    "Local structural XSD validation is distinct from clinical review and is not FDA SPL validation.",
]


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def x(tag: str) -> str:
    return f"{{{EXT}}}{tag}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def child(parent: ET.Element, name: str, text: str | None = None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, q(name), {k: str(v) for k, v in attrs.items()})
    element.text = text
    return element


def evidence(parent: ET.Element, doc_id: str, page: int, *, quote=None, block=None):
    attrs = {"documentRef": doc_id, "pageStart": str(page), "pageEnd": str(page)}
    if block:
        attrs["blockRef"] = block
    item = child(parent, "evidence", **attrs)
    if quote is not None:
        child(item, "quote", quote)
    return item


def fact(element: ET.Element, raw: str, doc_id: str, page: int, quote: str):
    element.clear()
    element.attrib.update(presence="present", derivation="extracted", reviewStatus="unreviewed")
    child(element, "textRaw", raw)
    evidence(element, doc_id, page, quote=quote, block=f"{doc_id}-page-{page:04d}-text")


def page_position(offset: int, starts: list[int], texts: list[str]) -> int:
    for index, (start, text) in enumerate(zip(starts, texts)):
        if start <= offset < start + len(text):
            return index + 1
    raise ValueError(f"Offset {offset} does not refer to a source character")


def extract(path: Path, root_dir: Path) -> dict:
    doc_id = "doc-" + path.stem.replace("_", "-")
    brand_key = path.stem.split("_")[0]
    with pymupdf.open(path) as pdf:
        texts = [page.get_text("text", sort=False) for page in pdf]
        page_metadata = [
            {"number": index + 1, "widthPoints": page.rect.width,
             "heightPoints": page.rect.height, "embeddedImageCount": len(page.get_images()),
             "pdfPageLabel": page.get_label()}
            for index, page in enumerate(pdf)
        ]
    for text in texts:
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", text):
            raise ValueError(f"XML 1.0-incompatible text in {path}; refusing silent character loss")
        if "\r" in text:
            raise ValueError(f"CR found in {path}; explicit lossless encoding is required")
    joined = "\n".join(texts)
    starts, running = [], 0
    for text in texts:
        starts.append(running)
        running += len(text) + 1
    marker = re.search(r"(?m)^[ \t]*FULL PRESCRIBING INFORMATION[ \t]*$", joined)
    # Only the identity title before Initial Approval is considered. This excludes
    # later biosimilar-reference statements and section references in parentheses.
    approval = re.search(r"Initial\s+U\.?S\.?\s+Approval:\s*(\d{4})", texts[0])
    title_area = texts[0][:approval.start()] if approval else texts[0][:1500]
    identity_matches = list(re.finditer(
        rf"(?im)^[ \t]*(?P<brand>{re.escape(brand_key)}(?: XR)?)[®™]?[ \t]*"
        r"\((?P<generic>[a-zA-Z][a-zA-Z0-9 -]+)\)[^\n]*", title_area))

    generic_names = {m.group("generic") for m in identity_matches}
    if len(generic_names) > 1:
        raise ValueError(f"Conflicting generic names in title: {path}")
    revisions = [(i + 1, m.group(0), m.group(1), m.group(2))
                 for i, text in enumerate(texts[:3])
                 for m in re.finditer(r"Revised:\s*(\d{1,2})/(\d{4})", text)]
    revision = revisions[0] if len({(v[2], v[3]) for v in revisions}) == 1 else None
    candidates = []
    if marker:
        for number, alternatives in HEADINGS.items():
            for title in alternatives:
                pattern = re.escape(title).replace(r"\ ", r"[ \t\n]+").replace("/", r"[ \t]*/[ \t]*")
                pattern = rf"(?m)^[ \t]*{number}\.?[ \t]*(?:\n[ \t]*)?{pattern}[ \t]*$"
                candidates.extend((m.start(), m.end(), number, m.group(0))
                                  for m in re.finditer(pattern, joined)
                                  if m.start() > marker.end())
        candidates.sort()
    numbers = [item[2] for item in candidates]
    if numbers != sorted(set(numbers)):
        raise ValueError(f"Ambiguous/duplicate full-PI section sequence in {path}: {numbers}")
    # Conservative coarse boundary, never a claim that each appended patient
    # document has been segmented or that the last candidate section is reviewed.
    appendix = None
    if candidates:
        tail = joined[candidates[-1][1]:]
        appendix = re.search(
            r"(?mi)^[ \t]*(?:PATIENT INFORMATION|MEDICATION GUIDE|INSTRUCTIONS FOR USE|"
            r"Information for the Patient/Caregiver)[ \t]*$", tail)
        if appendix:
            appendix = candidates[-1][1] + appendix.start()
    low = [i + 1 for i, text in enumerate(texts) if len(text.strip()) < 80]
    return {
        "id": doc_id, "productId": f"product-{brand_key}", "brandKey": brand_key,
        "path": path.relative_to(root_dir).as_posix(), "bytes": path.stat().st_size,
        "sha256": digest(path.read_bytes()), "texts": texts, "starts": starts,
        "joined": joined, "pageMetadata": page_metadata, "marker": marker,
        "identity": identity_matches[0] if identity_matches else None, "identities": identity_matches,
        "approval": approval, "revision": revision, "candidates": candidates,
        "appendixOffset": appendix, "lowTextPages": low,
    }


def add_fragment_section(raw: ET.Element, record: dict, key: str, kind: str,
                         begin: int, end: int, heading: str, number=None):
    section_id = f"{record['id']}-{key}"
    sec = child(raw, "section", id=section_id, kind=kind, presence="present", fidelity="unverified")
    sec.set(x("reviewStatus"), "unreviewed")
    sec.set(x("representation"), "derivedTextLayerSlice")
    h = child(sec, "heading", heading)
    h.set(XML_SPACE, "preserve")
    if number is not None:
        h.set("number", str(number))
    for i, (start, text) in enumerate(zip(record["starts"], record["texts"]), 1):
        lo, hi = max(begin, start) - start, min(end, start + len(text)) - start
        if hi <= lo:
            continue
        paragraph_id = f"{section_id}-p{i:04d}"
        fragment = text[lo:hi]
        paragraph = child(sec, "paragraph", fragment, id=paragraph_id)
        paragraph.set(XML_SPACE, "preserve")
        risks = []
        if re.search(r"(?im)^[ \t]*Table[ \t]+[0-9]", fragment): risks.append("unresolved_table")
        if re.search(r"(?im)^[ \t]*Figure[ \t]+[0-9]", fragment): risks.append("unresolved_figure")
        if risks: paragraph.set(x("warnings"), " ".join(risks))
        paragraph.set(x("sha256"), digest(fragment.encode("utf-8")))
        ev = evidence(sec, record["id"], i, block=f"{record['id']}-page-{i:04d}-text")
        ev.set(x("fragmentRef"), paragraph_id)
        ev.set(x("characterStart"), str(lo))
        ev.set(x("characterEndExclusive"), str(hi))
    return sec


def _assemble(root_dir: Path, template_path: Path, output_path: Path, report_path: Path, records):
    template = ET.parse(template_path).getroot()
    template_product = template.find("p:products/p:product", PREFIX)
    template_document = template.find("p:documents/p:document", PREFIX)
    root = copy.deepcopy(template)
    root.set("contentStatus", "machineExtractedUnreviewed")
    root.set(x("schemaValidation"), "localStructuralSchema")
    root.set(x("parserVersion"), "text-layer-sections-v2")
    root.set(x("templateSha256"), digest(template_path.read_bytes()))
    root.find(q("sourceIndex")).set(x("verificationStatus"), "templateReferenceNotVerified")
    products, documents = root.find(q("products")), root.find(q("documents"))
    products.clear()
    documents.clear()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = {}
    report_docs = []
    for record in records:
        doc_id, product_id = record["id"], record["productId"]
        match = record["identity"]
        if product_id not in seen:
            product = copy.deepcopy(template_product)
            product.set("id", product_id)
            if match:
                fact(product.find(q("brandName")), match.group("brand"), doc_id, 1, match.group(0))
                fact(product.find(q("genericName")), match.group("generic"), doc_id, 1, match.group(0))
            variant = product.find("p:variants/p:variant", PREFIX)
            variant.set("id", f"{product_id}-unresolved-variant")
            variant.set(x("status"), "placeholderNotAnIdentifiedPresentation")
            for alias in record["identities"][1:]:
                if alias.group("brand") != match.group("brand"):
                    extra = ET.SubElement(product.find(q("brandName")), x("additionalTitleBrand"))
                    extra.text = alias.group("brand")
                    evidence(extra, doc_id, 1, quote=alias.group(0), block=f"{doc_id}-page-0001-text")
            products.append(product)
            seen[product_id] = product
        else:
            product = seen[product_id]
            known = product.findtext("p:genericName/p:textRaw", namespaces=PREFIX)
            if match and known and known != match.group("generic"):
                raise ValueError(f"Conflicting product identity: {product_id}")
            if match:
                for field in ("brandName", "genericName"):
                    if product.find(q(field)).get("presence") == "unknown":
                        fact(product.find(q(field)), match.group("brand" if field == "brandName" else "generic"), doc_id, 1, match.group(0))
                    else:
                        evidence(product.find(q(field)), doc_id, 1, quote=match.group(0), block=f"{doc_id}-page-0001-text")
        document = copy.deepcopy(template_document)
        document.attrib.update(id=doc_id, contentStatus="machineExtractedUnreviewed", recordVersion="1")
        for item in document.iter():
            if item.get("id", "").startswith("template-"):
                item.set("id", doc_id + "-" + item.get("id").removeprefix("template-"))
        coverage = document.find(q("coverage"))
        coverage.clear()
        child(coverage, "productRef", ref=product_id, coverageStatus="unknown")
        source_scope = ET.SubElement(coverage, x("sourceScope"), {
            "basis": "suppliedFilename", "applicabilityStatus": "unverified",
            "key": Path(record["path"]).stem.removesuffix("_prescribing_information")})
        source_scope.text = Path(record["path"]).name
        acquisition = document.find(q("acquisition"))
        acquisition.clear()
        acquisition.set("status", "suppliedLocalFile")
        for name, value in (("localPath", record["path"]), ("mediaType", "application/pdf"),
                            ("byteSize", record["bytes"]), ("sha256", record["sha256"])):
            child(acquisition, name, str(value))
        metadata = document.find(q("labelMetadata"))
        metadata.clear()
        title = child(metadata, "documentTitle", presence="unknown", derivation="unassessed")
        if record["marker"]:
            marker = record["marker"]
            marker_page = page_position(marker.start(), record["starts"], record["texts"])
            fact(title, marker.group(0).strip(), doc_id, marker_page, marker.group(0))
        if record["approval"]:
            child(metadata, "initialApprovalYear", record["approval"].group(1))
        if record["revision"]:
            page, quote, month, year = record["revision"]
            child(metadata, "labelRevision", f"{year}-{int(month):02d}")
            evidence(metadata, doc_id, page, quote=quote, block=f"{doc_id}-page-{page:04d}-text")
        if record["approval"]:
            evidence(metadata, doc_id, 1, quote=record["approval"].group(0), block=f"{doc_id}-page-0001-text")
        child(metadata, "note", "Label revision preserves printed month precision; initial approval is a separate field. Current-label and document-version relationships have not been assessed.")
        raw = document.find(q("rawSections"))
        raw.clear()
        raw.set("coverage", "textLayerComplete")
        raw.set(x("clinicalStructureStatus"), "partialUnreviewed")
        for i, (text, page_meta) in enumerate(zip(record["texts"], record["pageMetadata"]), 1):
            page_id = f"{doc_id}-page-{i:04d}"
            sec = child(raw, "section", id=page_id, kind="sourcePageArchive", presence="present", fidelity="unverified")
            sec.set(x("pdfPage"), str(i))
            sec.set(x("representation"), "unalteredTextLayerSourceOrder")
            sec.set(x("pageExtractionStatus"), "textLayer" if text.strip() else "noUsableTextOcrUnavailable")
            for name in ("widthPoints", "heightPoints", "embeddedImageCount", "pdfPageLabel"):
                if page_meta[name] != "":
                    sec.set(x(name), str(page_meta[name]))
            child(sec, "heading", f"PDF page {i}: extracted text layer")
            paragraph = child(sec, "paragraph", text, id=f"{page_id}-text")
            paragraph.set(XML_SPACE, "preserve")
            paragraph.set(x("sha256"), digest(text.encode("utf-8")))
            paragraph.set(x("characterCount"), str(len(text)))
            evidence(sec, doc_id, i, block=f"{page_id}-text")
        candidates = record["candidates"]
        if record["marker"] and candidates:
            add_fragment_section(raw, record, "full-preamble", "fullPrescribingInformationPreamble",
                                 record["marker"].start(), candidates[0][0], "FULL PRESCRIBING INFORMATION: preamble (may include boxed warning)")
        if record["marker"] and record["marker"].start() > 0:
            add_fragment_section(raw, record, "highlights", "highlights", 0, record["marker"].start(), "Highlights and contents (candidate text order)")
        for index, (start, end, number, heading) in enumerate(candidates):
            limit = candidates[index + 1][0] if index + 1 < len(candidates) else (record["appendixOffset"] or len(record["joined"]))
            subs = list(re.finditer(rf"(?m)^[ \t]*({number}\.[0-9]+)[ \t]*(?:\n[ \t]*)?([A-Z][^\n]*)", record["joined"][end:limit]))
            # Repeated printed headings are ambiguous; keep the coarse section.
            if subs and len({m.group(1) for m in subs}) == len(subs):
                offset = end
                if subs[0].start() + offset > start:
                    add_fragment_section(raw, record, f"section-{number}-preamble", "fullPrescribingInformation", start, subs[0].start()+offset, heading, number)
                for sub_index, match in enumerate(subs):
                    sub_end = subs[sub_index+1].start()+offset if sub_index+1 < len(subs) else limit
                    add_fragment_section(raw, record, "section-"+match.group(1).replace(".","-"), "fullPrescribingInformation", match.start()+offset, sub_end, match.group(0), match.group(1))
            else:
                add_fragment_section(raw, record, f"section-{number}", "fullPrescribingInformation", start, limit, heading, number)
        if record["appendixOffset"] is not None:
            offset = record["appendixOffset"]
            matches = list(re.finditer(r"(?mi)^[ \t]*(MEDICATION GUIDE|INSTRUCTIONS FOR USE|PATIENT INFORMATION|Information for the Patient/Caregiver)[ \t]*$", record["joined"][offset:]))
            for appendix_index, match in enumerate(matches):
                appendix_end = matches[appendix_index+1].start()+offset if appendix_index+1<len(matches) else len(record["joined"])
                kind = {"MEDICATION GUIDE":"medicationGuide", "INSTRUCTIONS FOR USE":"instructionsForUse"}.get(match.group(1).upper(), "patientInformation")
                add_fragment_section(raw, record, f"appendix-{appendix_index+1}", kind, match.start()+offset, appendix_end, match.group(0))
        quality = document.find(q("extractionQuality"))
        quality.clear()
        quality.attrib.update(status="partial", method="deterministicTextLayerExtraction", reviewStatus="unreviewed", extractedAt=timestamp)
        child(quality, "toolName", "PyMuPDF; scripts/build_amgen_xml.py")
        child(quality, "toolVersion", pymupdf.VersionBind)
        child(quality, "pageCount", str(len(record["texts"])))
        child(quality, "pagesProcessed", str(len(record["texts"])))
        warnings = list(COMMON_WARNINGS)
        if record["lowTextPages"]:
            warnings.append(f"OCR unavailable; low-text pages (<80 stripped characters): {record['lowTextPages']}. They are retained; short text alone does not prove blankness.")
        if record["brandKey"] == "repatha":
            warnings.append("Both Repatha full PIs discuss rubber-containing and latex-free presentations. Source filename scopes remain separate; no blanket latex applicability or same-scope supersession is inferred.")
        if record["brandKey"] == "otezla":
            warnings.append("Title includes OTEZLA and OTEZLA XR. Release-form and regimen applicability have not been structurally resolved.")
        if not candidates:
            warnings.append("No reliable top-level sections detected; use the complete page archive.")
        for warning in warnings:
            child(quality, "issue", warning, severity="warning")
        documents.append(document)
        match = record["identity"]
        report_docs.append({
            "documentId": doc_id, "productId": product_id, "localPath": record["path"],
            "sourceSha256": record["sha256"], "byteSize": record["bytes"],
            "pageCount": len(record["texts"]), "pagesProcessed": len(record["texts"]),
            "rawTextCharacters": sum(map(len, record["texts"])),
            "candidateTopLevelSections": [item[2] for item in candidates],
            "brandName": match.group("brand") if match else None, "genericName": match.group("generic") if match else None,
            "labelRevision": metadata.findtext(q("labelRevision")),
            "lowTextPages": record["lowTextPages"],
            "emptyTextPages": [i + 1 for i, text in enumerate(record["texts"]) if not text.strip()],
            "sourceScopeKey": source_scope.get("key"), "warnings": warnings,
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Only container indentation is changed; paragraph text remains a leaf value.
    # validate() proves every page survives serialization without text changes.
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    from .xml_store import load_corpus, validate_schema
    load_corpus(output_path)
    validate_schema(output_path)
    checks = {"status": "passed", "xsdValidated": True, "schemaScope": "localStructural", "clinicalReview": "unreviewed"}
    report = {
        "generatedAt": timestamp, "artifact": str(output_path),
        "artifactSha256": digest(output_path.read_bytes()),
        "template": str(template_path),
        "templateSha256": digest(template_path.read_bytes()),
        "scriptSha256": digest(Path(__file__).read_bytes()),
        "pythonVersion": sys.version.split()[0], "pymupdfVersion": pymupdf.VersionBind,
        "status": "firstPassTextExtractionUnreviewed", "schemaValidation": "localStructuralSchemaPassed",
        "counts": {"products": len(seen), "documents": len(records),
                   "pages": sum(len(r["texts"]) for r in records),
                   "candidateTopLevelSections": sum(len(r["candidates"]) for r in records),
                   "rawTextCharacters": sum(sum(map(len, r["texts"])) for r in records),
                   "lowTextPages": sum(len(r["lowTextPages"]) for r in records)},
        "validation": checks, "warnings": COMMON_WARNINGS, "documents": report_docs,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


class CorpusBuildError(ValueError):
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _atomic_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build_corpus(source_dir: Path, output_path: Path) -> BuildReport:
    """Build completely locally, preserving the prior artifact on any failure.

    No missing/corrupt input silently disappears. Failed builds raise with an
    attached BuildReport. Source page text remains exactly sort=False extraction.
    """
    from .xml_store import load_corpus
    source_dir, output_path = Path(source_dir).resolve(), Path(output_path).resolve()
    root_dir = source_dir.parent
    report = BuildReport(str(output_path), "", 0, 0, 0, 0, False)
    try:
        paths = sorted(p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    except OSError:
        raise CorpusBuildError("Unable to read the source PDF directory; previous XML retained.", report) from None
    report.input_count = len(paths)
    records = []
    for path in paths:
        try:
            record = extract(path, root_dir)
            # XML IDs must remain safe even for filenames with spaces/punctuation.
            safe = re.sub(r"[^A-Za-z0-9_.-]", "-", path.stem.replace("_", "-"))
            record["id"] = "doc-" + safe
            record["productId"] = "product-" + re.sub(r"[^a-z0-9.-]", "-", record["brandKey"].lower())
            records.append(record)
        except Exception as error:
            report.failed_files.append({"filename": path.name, "error": type(error).__name__})
    report.document_count = len(records)
    report.product_count = len({r["productId"] for r in records})
    report.page_count = sum(len(r["texts"]) for r in records)
    if not paths or report.failed_files:
        raise CorpusBuildError("No inputs or one or more PDFs could not be extracted; previous XML retained.", report)
    seen_hashes = {}
    for record in records:
        if record["sha256"] in seen_hashes:
            report.warnings.append("Duplicate source content retained: " + Path(record["path"]).name + " / " + seen_hashes[record["sha256"]])
        seen_hashes[record["sha256"]] = Path(record["path"]).name
    if len({r["id"] for r in records}) != len(records):
        raise CorpusBuildError("Source filenames produce duplicate XML IDs; rename inputs explicitly.", report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).resolve().parents[1] / "XML" / "prescribing-information-template.xml"
    with tempfile.TemporaryDirectory(prefix=".corpus-build-", dir=output_path.parent) as stage:
        staged = Path(stage) / "corpus.xml"
        raw_report = _assemble(root_dir, template, staged, Path(stage) / "report.json", records)
        corpus = load_corpus(staged)
        # Verify extraction roundtrip and source hashes before publication.
        archived = {(b.document_id, b.page_start): b.text for b in corpus.blocks if b.section_kind == "sourcePageArchive"}
        for record in records:
            if digest((root_dir / record["path"]).read_bytes()) != record["sha256"]:
                raise CorpusBuildError("Source changed during build; previous XML retained.", report)
            for number, text in enumerate(record["texts"], 1):
                if archived.get((record["id"], number)) != text:
                    raise CorpusBuildError("Source page text did not roundtrip; previous XML retained.", report)
        payload = staged.read_bytes()
        if output_path.exists():
            previous = output_path.read_bytes()
            snapshot = output_path.parent / "snapshots" / (digest(previous) + ".xml")
            _atomic_bytes(snapshot, previous)
            report.snapshot_path = str(snapshot)
            # Repeating an identical extraction must not invalidate evaluation,
            # preview or published-corpus pins solely because the clock advanced.
            # Preserve exact bytes only when every non-time artifact byte agrees.
            without_time = lambda value: re.sub(rb' extractedAt="[^"]*"', b'', value)
            if without_time(payload) == without_time(previous):
                payload = previous
        report.xml_hash = digest(payload)
        report.block_count = len(corpus.blocks)
        report.schema_valid = True
        report.schema_status = "localStructuralSchemaPassed"
        report.warnings.extend(COMMON_WARNINGS)
        raw_report.update(artifact=str(output_path), artifactSha256=report.xml_hash, buildReport=asdict(report))
        _atomic_bytes(output_path, payload)
        _atomic_bytes(output_path.with_suffix(".report.json"), (json.dumps(raw_report, ensure_ascii=False, indent=2) + "\n").encode())
    return report
