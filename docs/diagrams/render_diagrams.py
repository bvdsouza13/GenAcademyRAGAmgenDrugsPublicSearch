#!/usr/bin/env python3
"""Editable diagrams for the bulk-library Amgen Medicine Explorer.

Run from the project root:
    .venv-corpus/bin/python docs/diagrams/render_diagrams.py

SVGs use ordinary editable vector shapes and text. PNG rendering uses PyMuPDF,
already available in .venv-corpus. No Graphviz or network access is required.
The diagrams describe application contracts, not measured cloud-release outcomes.
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
            f'<desc id="desc">{escape(subtitle)} Local bulk-library architecture. Release verification and clinical review are separate.</desc>',
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
        self.text(60, self.height - 26, "LOCAL IMPLEMENTATION  •  11 NOV 2026  •  Blue = application / service exchange; amber = source or release constraint", 15, MUTED)

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
    d = Diagram("01-solution-architecture", "01", "Whole-library solution architecture", "One registered library, global content discovery and version-pinned source teaching")
    d.rect(60, 185, 1560, 142, NAVY, NAVY)
    d.text(85, 222, "LOCAL STREAMLIT EXPERIENCE", 18, WHITE, 700)
    for x, title, detail in [(85, "Search & Learn", "Body text, names, source excerpts"), (600, "Admin: Library", "Build / update entire collection"), (1115, "Chunk experiments", "Test, Use, Default, Restore, Revert")]:
        d.text(x, 264, title, 24, WHITE, 700)
        d.text(x, 298, detail, 18, "#C7E7FF")
    d.rect(60, 395, 1130, 490, ICE, LINE)
    d.text(85, 431, "LOCAL PYTHON APPLICATION", 18, BLUE, 700)
    d.arrow([(355, 327), (355, 395)])
    d.text(375, 352, "Explicit submissions; rerenders do not call providers", 18, MUTED)
    d.card(85, 458, 340, 221, "Complete source preparation", [
        "Authoritative source registry", "PDF identity + exact XML spans", "Versioned automatic eligibility",
        "All readable page intervals", "Source-scoped chunks: 600 / 80",
    ], body=17.5)
    d.card(455, 458, 340, 221, "Build, search and activation", [
        "New namespace + checkpoints", "Matching SQLite lexical artifact", "FTS5 / deterministic fallback",
        "Verify both; activate together", "Retain previous full library",
    ], body=17.5)
    d.card(825, 458, 340, 221, "Discovery and teaching", [
        "Global lexical + semantic fusion", "Group medicine / document hits", "Ask one selected source",
        "Pin run through chat and quiz", "Check support; cite snapshot PDF",
    ], body=17.5)
    d.arrow([(425, 568), (455, 568)])
    d.arrow([(795, 568), (825, 568)])
    for x in [255, 625, 995]:
        d.arrow([(x, 679), (x, 722)], both=True)
    d.card(85, 722, 1080, 135, "Local evidence and durable state", [
        "Original PDFs / canonical XML / immutable source snapshots / source registry history",
        "Ingestion SQLite / retained manual reviews / run records + lexical artifacts / atomic active pointer",
    ], body=18, gap=31)
    d.card(1250, 395, 370, 225, "Pinecone Documents API", [
        "Integrated llama-text-embed-v2", "1,024 dimensions / cosine", "Chunk text + flat metadata",
        "Whole-library namespaces", "Verified global / scoped searches",
    ], fill=ICE, body=17.5)
    d.arrow([(625, 458), (625, 368), (1435, 368), (1435, 395)])
    d.text(1050, 353, "Explicit text uploads / HTTPS", 17, BLUE, anchor="middle")
    d.arrow([(1165, 580), (1250, 580)], both=True)
    d.text(1207, 537, "Search", 14, BLUE, anchor="middle")
    d.card(1250, 680, 370, 177, "OpenAI Responses API", [
        "Question + source-scoped excerpts", "Explanation / cited support checks", "store=false; no full PDF upload",
    ], fill=ICE, body=17)
    d.arrow([(1165, 643), (1215, 643), (1215, 769), (1250, 769)], both=True)
    d.footer(956, [
        "Supplied inventory: 37 PDFs / 36 medicines. Actual searchable counts come from a verified complete run.",
        "Source verification establishes extraction provenance, not clinical approval. Admin is a local workflow, not hosted authorization.",
    ])
    d.save()


def data_flow():
    d = Diagram("02-data-flow", "02", "Build, discover and compare", "Whole-library versions retain exact source evidence through search, teaching and rollback", height=1550)
    cols = [85, 390, 695, 1000, 1305]
    width = 275
    d.rect(60, 185, 1560, 505, ICE, LINE)
    d.text(85, 224, "A  BUILD / UPDATE ENTIRE LIBRARY", 23, NAVY, 700)
    top = [
        ("1  Registered PDFs", ["All expected sources", "Missing files block release", "Uploads stay local"], WHITE, LINE),
        ("2  Single XML", ["Build / reuse exact sources", "Page archives + sections", "Original PDFs retained"], WHITE, LINE),
        ("3  Verify provenance", ["Hashes, ownership, spans", "Unique readable intervals", "No passage acceptance"], AMBER, AMBER_LINE),
        ("4  Prepare all text", ["Sections + archive gap fill", "Safe source continuations", "Layout warnings retained"], WHITE, LINE),
        ("5  Pin run records", ["Immutable records + XML", "Retained source snapshots", "Same policy / source identity"], WHITE, LINE),
    ]
    for x, (title, lines, fill, stroke) in zip(cols, top):
        d.card(x, 268, width, 158, title, lines, fill, stroke, 20, 17, 27)
    for x in cols[:-1]:
        d.arrow([(x+width,347),(x+305,347)])
    lower = [
        ("10  Ready", ["Actual searchable counts", "One full library version", "Previous version retained"], WHITE, BLUE),
        ("9  Atomic activation", ["Select semantic + lexical", "One active manifest", "Failure keeps old library"], WHITE, BLUE),
        ("8  Check search", ["Exact records + every doc", "Full inventory + coverage", "Local artifact validation"], AMBER, AMBER_LINE),
        ("7  Local lexical", ["SQLite FTS5 if available", "Deterministic fallback", "Run + ranking identity"], WHITE, LINE),
        ("6  Upload chunks", ["New Pinecone namespace", "Resumable batch writes", "Text + flat metadata"], "#DCEEFE", BLUE),
    ]
    for x, (title, lines, fill, stroke) in zip(cols, lower):
        d.card(x, 475, width, 158, title, lines, fill, stroke, 20, 17, 27)
    d.arrow([(1442,426),(1442,475)])
    for x in cols[1:]:
        d.arrow([(x,554),(x-30,554)])
    d.text(85, 667, "Automatic extraction verification is not human/clinical approval. Blank or image-only pages are reported; OCR is outside scope.", 17.5, MUTED)
    d.rect(60, 730, 1560, 280, WHITE, LINE)
    d.text(85, 769, "B  EXPLICIT GLOBAL DISCOVERY → ONE SELECTED SOURCE", 23, NAVY, 700)
    query = [
        ("Submit content query", ["Body / heading / brand", "Generic names included", "Medicine choice optional"], WHITE, LINE),
        ("Pin verified run", ["Check immutable records", "Check lexical artifact", "Use pinned XML catalog"], WHITE, LINE),
        ("Fuse verified ranks", ["Local + semantic search", "Bounded name boost", "Labeled degraded fallback"], "#DCEEFE", BLUE),
        ("Grouped sources", ["Deduplicate overlap", "Keep source variants apart", "View / Ask about source"], WHITE, LINE),
        ("Scoped teaching", ["Pinned product + doc + run", "Checked OpenAI explanation", "Snapshot PDF citations"], "#DCEEFE", BLUE),
    ]
    for x, (title, lines, fill, stroke) in zip(cols, query):
        d.card(x, 804, width, 158, title, lines, fill, stroke, 20, 17, 27)
    for x in cols[:-1]:
        d.arrow([(x+width,883),(x+305,883)])
    d.text(85, 988, "Activation affects fresh searches; existing conversations, quizzes and citations keep their selected library version.", 18, MUTED)
    d.rect(60, 1050, 1560, 270, ICE, LINE)
    d.text(85, 1089, "C  CONTROLLED CHUNK EXPERIMENT", 23, NAVY, 700)
    controls = [
        ("Draft 600 / 80", ["Conservative byte budgets", "Preview runs locally", "Not exact model tokens"]),
        ("Test settings", ["Explicit full-library build", "Isolated candidate", "Same sources and policy"]),
        ("Equal evaluation", ["Same suite / search profile", "Equal evidence budget", "Recall / spans / latency"]),
        ("Use configuration", ["Verified candidate only", "Atomic pointer change", "All medicines remain"]),
        ("Reset / Revert", ["Defaults: draft controls only", "Restore: current controls", "Revert: prior full library"]),
    ]
    for x,(title,lines) in zip(cols,controls):
        d.card(x,1124,width,158,title,lines,WHITE,LINE,20,17,27)
    for x in cols[:-1]:
        d.arrow([(x+width,1203),(x+305,1203)])
    d.footer(1370, [
        "Provider usage occurs only on explicit build/search/evaluate/teach actions. Default/current control resets call no provider.",
        "Retrieval observations and source provenance do not establish clinical accuracy. Retain all version artifacts for old citations.",
    ])
    d.save()


def deployment():
    d = Diagram("03-deployment", "03", "Local deployment and durable versions", "A local browser and Python server; retained source artifacts; two server-side provider integrations")
    d.rect(60,190,1030,735,ICE,LINE)
    d.text(85,232,"USER COMPUTER / LOCAL RUNTIME",22,NAVY,700)
    d.rect(1160,190,460,735,"#F5F9FC",LINE,dashed=True)
    d.text(1185,232,"REMOTE PROVIDER BOUNDARY",21,NAVY,700)
    d.card(90,285,400,190,"Local browser",[
        "Search & Learn / Admin", "Session learning and prepared demo", "Keys stay in server-side Python",
    ],body=18)
    d.card(600,285,450,240,"Python + Streamlit",[
        "127.0.0.1:8501 / local process", "Whole-library build + search + teach", "Explicit submissions; persisted jobs",
        "Run-pinned chat, quiz and citations", "Local operator controls; no hosted auth",
    ],body=18)
    d.arrow([(490,374),(600,374)],both=True)
    d.lines(514,329,["Local","HTTP"],17,BLUE,23)
    d.card(90,620,450,245,"Durable local evidence",[
        "Registered Documents/*.pdf", "Canonical XML + immutable snapshots", "Source registry + version history",
        "Run records + SQLite lexical artifacts", "Review/job SQLite + active manifest",
    ],body=18)
    d.card(600,620,450,245,"Server-side configuration",[
        "config/app.toml: unchanged structure", "Ignored secrets TOML / exported keys", "Nonblank environment values win",
        "No .env loader; no automatic indexing", "Keep data/ for citations and rollback",
    ],body=18)
    d.arrow([(670,525),(670,560),(315,560),(315,620)],both=True)
    d.text(360,549,"Evidence / checkpoints / artifact validation",16,BLUE)
    d.arrow([(825,620),(825,525)])
    d.text(845,584,"Settings + credentials",17,BLUE)
    d.card(1190,285,400,250,"Pinecone Documents API",[
        "Integrated llama-text-embed-v2", "1,024 dimensions / cosine", "Chunks + compact flat metadata",
        "Whole-library version namespaces", "Global / source-scoped queries", "No full PDF or XML uploads",
    ],body=18,gap=28)
    d.arrow([(1050,374),(1190,374)],both=True)
    d.text(1120,355,"HTTPS",18,BLUE,anchor="middle")
    d.card(1190,650,400,185,"OpenAI Responses API",[
        "Question + selected scoped excerpts", "Checked source-backed explanations", "store=false / no full PDF uploads",
    ],body=18)
    d.arrow([(1050,475),(1120,475),(1120,743),(1190,743)],both=True)
    d.rect(1091,597,58,28,WHITE,WHITE,3)
    d.text(1120,618,"HTTPS",18,BLUE,anchor="middle")
    d.footer(956,[
        "Retained snapshots and manifests keep old conversations resolvable. Semantic and lexical versions activate together.",
        "Shared hosting is outside scope: it needs server-enforced roles, durable shared storage, learner isolation and operational recovery.",
    ])
    d.save()


if __name__ == "__main__":
    architecture()
    data_flow()
    deployment()
