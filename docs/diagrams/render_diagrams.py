#!/usr/bin/env python3
"""Editable diagram source for the proposed Amgen Medicine Explorer.

Run from the project root:
    .venv-corpus/bin/python docs/diagrams/render_diagrams.py

SVGs use ordinary editable vector shapes and text. PNG rendering uses PyMuPDF,
already available in .venv-corpus. No Graphviz or network access is required.
The diagrams describe a proposed application; they do not claim a live deployment.
"""

from html import escape
from math import hypot
from pathlib import Path

import fitz


OUT = Path(__file__).resolve().parent
BLUE = "#0063C3"
NAVY = "#072B50"
INK = "#153B5C"
MUTED = "#4D667B"
ICE = "#EEF6FC"
LINE = "#B8D2E8"
AMBER = "#FFF5DF"
AMBER_LINE = "#C18A29"
WHITE = "#FFFFFF"


class Diagram:
    def __init__(self, filename, number, title, subtitle, height=1120):
        self.filename = filename
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1680" height="{height}" viewBox="0 0 1680 {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(title)}</title>',
            f'<desc id="desc">{escape(subtitle)} Implemented local architecture. Source-fidelity pilot is published; broad clinical review remains separate.</desc>',
            '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M 0 0 L 9 4.5 L 0 9 z" fill="#0063C3"/></marker></defs>',
            '<style>text { font-family: Helvetica, Arial, sans-serif; } .body { font-size: 19px; } </style>',
            f'<rect width="1680" height="{height}" fill="{WHITE}"/>',
            f'<rect width="1680" height="12" fill="{BLUE}"/>',
        ]
        self.text(60, 58, f"AMGEN MEDICINE EXPLORER  /  {number}", 16, BLUE, weight=700)
        self.text(60, 109, title, 39, NAVY, weight=700)
        self.text(60, 146, subtitle, 20, MUTED)

    def text(self, x, y, text, size=19, color=INK, weight=400, anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" font-family="Helvetica, Arial, sans-serif" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(text)}</text>')

    def rect(self, x, y, w, h, fill=WHITE, stroke=LINE, radius=14, dashed=False):
        dash = ' stroke-dasharray="8 5"' if dashed else ''
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>')

    def lines(self, x, y, lines, size=19, color=INK, gap=29, weight=400):
        for i, line in enumerate(lines):
            self.text(x, y + i * gap, line, size, color, weight)

    def card(self, x, y, w, h, title, lines, fill=WHITE, stroke=LINE, heading=22, body=19, gap=29):
        self.rect(x, y, w, h, fill, stroke)
        self.parts.append(f'<rect x="{x}" y="{y + 20}" width="5" height="29" rx="2" fill="{stroke if stroke == AMBER_LINE else BLUE}"/>')
        self.text(x + 22, y + 42, title, heading, NAVY, 700)
        self.lines(x + 22, y + 79, lines, body, INK, gap)

    def arrow(self, points, both=False, dashed=False):
        path = "M " + " L ".join(f"{x} {y}" for x, y in points)
        dash = ' stroke-dasharray="7 5"' if dashed else ''
        self.parts.append(f'<path d="{path}" fill="none" stroke="{BLUE}" stroke-width="2.5" stroke-linejoin="round"{dash}/>')
        # Explicit polygons work in SVG editors and PyMuPDF, whose SVG renderer
        # does not render marker-end / marker-start consistently.
        ends = [(points[-1], points[-2])]
        if both:
            ends.append((points[0], points[1]))
        for (x, y), (px, py) in ends:
            length = hypot(x - px, y - py)
            ux, uy = (x - px) / length, (y - py) / length
            bx, by = x - 10 * ux, y - 10 * uy
            triangle = f"{x},{y} {bx - 5 * uy},{by + 5 * ux} {bx + 5 * uy},{by - 5 * ux}"
            self.parts.append(f'<polygon points="{triangle}" fill="{BLUE}"/>')

    def footer(self, y, lines):
        self.rect(60, y, 1560, 93, AMBER, "#E7C990", 12)
        self.lines(82, y + 34, lines, 19, INK, 29)
        self.text(60, self.height - 26, "LOCAL IMPLEMENTATION  •  11 NOV 2026  •  Blue = application / service exchange; amber = review or current-state constraint", 15, MUTED)

    def save(self):
        svg = "\n".join(self.parts + ["</svg>"])
        svg_path = OUT / (self.filename + ".svg")
        svg_path.write_text(svg, encoding="utf-8")
        doc = fitz.open(stream=svg.encode(), filetype="svg")
        # Render via an intermediate PDF because SVG is a reflowable input.
        pdf = fitz.open("pdf", doc.convert_to_pdf())
        pdf[0].get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False).save(OUT / (self.filename + ".png"))
        print(f"Rendered {self.filename}.svg and .png")


def architecture():
    d = Diagram("01-solution-architecture", "01", "Solution architecture", "Responsibilities, evidence ownership and service boundaries")
    d.rect(60, 185, 1560, 142, NAVY, NAVY)
    d.text(85, 222, "STREAMLIT EXPERIENCE  ·  IMPLEMENTED", 18, WHITE, 700)
    for x, title, detail in [(85, "Explore medicines", "Browse the source library"), (600, "Learn with chat", "Lessons, questions and PDF citations"), (1115, "Manage sources", "Local operator actions")]:
        d.text(x, 264, title, 24, WHITE, 700)
        d.text(x, 298, detail, 19, "#C7E7FF")

    d.rect(60, 395, 1130, 490, ICE, LINE)
    d.text(85, 431, "LOCAL PYTHON APPLICATION  ·  IMPLEMENTED", 18, BLUE, 700)
    d.arrow([(355, 327), (355, 395)])
    d.text(375, 352, "Local UI calls application services", 18, MUTED)

    d.card(85, 458, 340, 221, "Source preparation", [
        "Existing PDF → XML extractor",
        "Hash-bound passage review",
        "Section-aware chunking",
        "600 / 80 conservative budgets",
        "Local previews; no upload",
    ], body=18)
    d.card(455, 458, 340, 221, "Index and publication", [
        "Preflight and explicit load",
        "Batch writes + checkpoints",
        "New staged namespace",
        "Verify → explicit publication",
        "Retain previous build",
    ], body=18)
    d.card(825, 458, 340, 221, "Learning and citations", [
        "Pin one active corpus per answer",
        "Resolve medicine / variant scope",
        "Retrieve reviewed evidence",
        "OpenAI generates explanation",
        "Validate claims and PDF citations",
    ], body=17.8)
    d.arrow([(425, 568), (455, 568)])
    d.arrow([(795, 568), (825, 568)])
    for x in [255, 625, 995]:
        d.arrow([(x, 679), (x, 722)], both=True)

    d.card(85, 722, 1080, 135, "Local evidence and durable state", [
        "Original PDFs • canonical XML • immutable corpus snapshots • citation resolver",
        "SQLite review / job state • chunk and ingestion manifests • active-build information",
    ], body=20, gap=31)

    d.card(1250, 395, 370, 225, "Pinecone · connected", [
        "Serverless Documents API",
        "Integrated llama-text-embed-v2",
        "1,024 dimensions • cosine",
        "Reviewed text + flat metadata",
        "Staged and active namespaces",
    ], fill=ICE, body=18)
    d.arrow([(625, 458), (625, 368), (1435, 368), (1435, 395)])
    d.text(1050, 353, "Reviewed chunk batches · HTTPS", 17, BLUE, anchor="middle")
    d.arrow([(1165, 580), (1250, 580)], both=True)
    d.text(1207, 537, "Scoped", 15, BLUE, anchor="middle")
    d.text(1207, 558, "search", 15, BLUE, anchor="middle")

    d.card(1250, 680, 370, 177, "OpenAI API · connected", [
        "Input: question + retrieved excerpts",
        "Output: generated explanation",
        "Local service checks citations",
    ], fill=ICE, body=18)
    d.arrow([(1165, 643), (1215, 643), (1215, 769), (1250, 769)], both=True)
    d.text(1435, 655, "HTTPS · evidence-backed generation", 17, BLUE, anchor="middle")

    d.footer(956, [
        "Current assets: 37 PDFs • 36 product identities • 1,439 pages • scripts/build_amgen_xml.py → XML/AmgenProducts.xml.",
        "XML structure and provenance are validated. Chat uses only reviewed, published evidence; most passages remain unreviewed.",
    ])
    d.save()


def data_flow():
    d = Diagram("02-data-flow", "02", "Data flow", "Two separate flows: operator-controlled publication and a scoped, cited answer", height=1240)
    d.rect(60, 185, 1560, 535, ICE, LINE)
    d.text(85, 224, "A  PREPARE AND PUBLISH A CORPUS", 23, NAVY, 700)
    d.text(85, 254, "Local work stays local until the operator selects Load Pinecone. Blue cloud cards identify remote processing.", 19, MUTED)
    cols = [85, 390, 695, 1000, 1305]
    width = 275
    top = [
        ("1  Source PDFs", ["37 files / 36 products", "1,439 physical pages", "Original bytes retained"], WHITE, LINE),
        ("2  Build XML", ["Existing local Python script", "One consolidated collection", "First-pass / unreviewed"], WHITE, LINE),
        ("3  Review gate", ["Check against source PDF", "Approve exact passages", "Hash-bound decisions"], AMBER, AMBER_LINE),
        ("4  Chunk settings", ["Section-aware boundaries", "Target 600 / overlap 80", "Preserve scope + qualifiers"], WHITE, LINE),
        ("5  Local preview", ["Inspect exact chunk text", "Counts, tokens, exclusions", "Pin XML + review snapshot"], WHITE, LINE),
    ]
    for x, (title, lines, fill, stroke) in zip(cols, top):
        d.card(x, 285, width, 158, title, lines, fill, stroke, 21, 17.5, 27)
    for x in cols[:-1]:
        d.arrow([(x + width, 364), (x + 305, 364)])
    lower = [
        ("10  Active corpus", ["Concrete namespace + hash", "Previous build retained", "Ready for scoped retrieval"], WHITE, BLUE),
        ("9  Explicit publish", ["Operator activates build", "Update active-build pointer", "data/active-corpus.json"], WHITE, BLUE),
        ("8  Verify readiness", ["Expected IDs and hashes", "Records visible to search", "Failed build stays inactive"], AMBER, AMBER_LINE),
        ("7  Staged namespace", ["Pinecone Documents API", "Integrated embedding", "Chunk text + flat metadata"], "#DCEEFE", BLUE),
        ("6  Explicit load", ["Preflight configuration", "Submit displayed batch", "Persist resumable progress"], WHITE, LINE),
    ]
    for x, (title, lines, fill, stroke) in zip(cols, lower):
        d.card(x, 495, width, 158, title, lines, fill, stroke, 21, 17.5, 27)
    d.arrow([(1442, 443), (1442, 495)])
    for x in cols[1:]:
        d.arrow([(x, 574), (x - 30, 574)])
    d.text(85, 690, "Review decisions, chunk settings, build hashes and batch checkpoints are persisted locally. Rebuilds never auto-publish.", 19, MUTED)

    d.rect(60, 760, 1560, 309, WHITE, LINE)
    d.text(85, 799, "B  ANSWER A LEARNER", 23, NAVY, 700)
    d.text(85, 829, "Each answer uses one pinned, verified corpus through retrieval and citation resolution.", 19, MUTED)
    query = [
        ("1  Ask a question", ["Selected medicine + question", "Resolve ambiguous scope", "Local Streamlit session"], WHITE, LINE),
        ("2  Pin active build", ["Resolve concrete namespace", "Pin XML hash for this answer", "No mixed corpus versions"], WHITE, LINE),
        ("3  Retrieve evidence", ["Pinecone scoped search", "Product / variant filters", "Return reviewed passages"], "#DCEEFE", BLUE),
        ("4  Draft explanation", ["OpenAI API", "Question + selected evidence", "Plain language or technical"], "#DCEEFE", BLUE),
        ("5  Validate and cite", ["Check claim / source support", "Show explanation + citations", "Resolve original PDF page"], WHITE, LINE),
    ]
    for x, (title, lines, fill, stroke) in zip(cols, query):
        d.card(x, 858, width, 158, title, lines, fill, stroke, 21, 17.5, 27)
    for x in cols[:-1]:
        d.arrow([(x + width, 937), (x + 305, 937)])
    d.text(85, 1046, "Missing or conflicting evidence produces a visible limitation. Citations resolve against the retained build and original PDF.", 19, MUTED)
    d.footer(1100, [
        "Remote payloads: Pinecone receives reviewed chunk text + compact metadata; OpenAI receives the question + retrieved excerpts.",
        "Original PDFs and canonical XML remain local. A verified six-chunk pilot is published; broader source review remains required.",
    ])
    d.save()


def deployment():
    d = Diagram("03-deployment", "03", "Local deployment design", "One local Python process, durable local evidence, and two server-side HTTPS integrations")
    d.rect(60, 190, 1030, 735, ICE, LINE)
    d.text(85, 232, "USER’S COMPUTER  ·  LOCAL RUNTIME PLANNED", 22, NAVY, 700)
    d.rect(1160, 190, 460, 735, "#F5F9FC", LINE, dashed=True)
    d.text(1185, 232, "REMOTE SERVICES  ·  IMPLEMENTED", 21, NAVY, 700)

    d.card(90, 285, 400, 190, "Browser on this computer", [
        "Explore / Learn / Manage sources",
        "Rendered pages and cited responses",
        "Provider API keys never enter browser",
    ], body=18.5)
    d.card(600, 285, 450, 240, "Python + Streamlit", [
        "localhost:8501 • one local process",
        "UI / source review / chunking / indexing",
        "Retrieval / generation / citation service",
        "Checkpointed jobs + ingestion lock",
        "Local operator mode for source controls",
    ], body=18.5)
    d.arrow([(490, 374), (600, 374)], both=True)
    d.lines(514, 329, ["Local", "HTTP"], 17, BLUE, 23)

    d.card(90, 620, 450, 245, "Local files and durable state", [
        "Existing: Documents/*.pdf",
        "Existing: XML/AmgenProducts.xml",
        "Planned: corpus snapshots + manifests",
        "Planned: SQLite review and job ledger",
        "Original PDF pages resolve locally",
    ], body=18.5)
    d.card(600, 620, 450, 245, "Server-side configuration", [
        "config/app.toml • non-secret settings",
        ".streamlit/secrets.toml • provider keys",
        "Environment variables override secrets",
        "Config loader + offline checks exist",
        "Keys are used only by the local server",
    ], body=18.5)
    d.arrow([(670, 525), (670, 560), (315, 560), (315, 620)], both=True)
    d.text(360, 549, "Read / write evidence and checkpoints", 17, BLUE)
    d.arrow([(825, 620), (825, 525)])
    d.text(845, 584, "Settings + credentials", 17, BLUE)

    d.card(1190, 285, 400, 250, "Pinecone", [
        "Serverless Documents API",
        "Integrated llama-text-embed-v2",
        "1,024 dimensions • cosine",
        "Reviewed chunks + flat metadata",
        "Queries and returned passages",
        "Staged / active namespaces",
    ], fill=WHITE, body=18.5, gap=28)
    d.arrow([(1050, 374), (1190, 374)], both=True)
    d.text(1120, 355, "HTTPS", 18, BLUE, anchor="middle")
    d.card(1190, 650, 400, 185, "OpenAI API", [
        "Question + retrieved evidence",
        "Returns generated explanations",
        "Local service validates citations",
    ], fill=WHITE, body=18.5)
    d.arrow([(1050, 475), (1120, 475), (1120, 743), (1190, 743)], both=True)
    d.rect(1091, 597, 58, 28, WHITE, WHITE, 3)
    d.text(1120, 618, "HTTPS", 18, BLUE, anchor="middle")
    d.text(1185, 891, "No full PDFs uploaded by this design", 18, MUTED)

    d.footer(956, [
        "Deployment status: proposed local runtime; no live Streamlit app, connected Pinecone corpus or OpenAI integration is claimed.",
        "Existing assets are the source PDFs, local extractor and first-pass XML. Hosted deployment is outside the first-version scope.",
    ])
    d.save()


if __name__ == "__main__":
    architecture()
    data_flow()
    deployment()
