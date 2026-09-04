"""Gera TECH_STACK.pdf — backlog de tecnologias, agrupado por categoria.

Uso:  python scripts/gerar_tech_stack_pdf.py
Saída: TECH_STACK.pdf na raiz do repositório.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "TECH_STACK.pdf"

VERDE = HexColor("#2E7D32")
CINZA = HexColor("#424242")
CINZA_CLARO = HexColor("#757575")

CATEGORIAS: list[tuple[str, list[str]]] = [
    (
        "Linguagem e runtime",
        [
            "Python 3.11",
        ],
    ),
    (
        "Backend / API",
        [
            "FastAPI",
            "Uvicorn",
            "Starlette",
            "Pydantic",
            "python-multipart",
            "python-dotenv",
        ],
    ),
    (
        "Banco de dados",
        [
            "PostgreSQL 17",
            "Neon (Postgres serverless)",
            "psycopg 3",
            "psycopg_pool",
            "BYTEA + TOAST",
            "Generated Columns (STORED)",
        ],
    ),
    (
        "Visão computacional e captura",
        [
            "OpenCV (opencv-python)",
            "NumPy",
            "HSV color segmentation",
            "V4L2 (Linux)",
            "MSMF (Windows)",
        ],
    ),
    (
        "APIs e serviços externos",
        [
            "Open-Meteo API",
            "WMO Weather Codes",
            "HTTP requests",
        ],
    ),
    (
        "Testes",
        [
            "pytest",
            "httpx",
            "FastAPI TestClient",
        ],
    ),
    (
        "Deploy e infraestrutura",
        [
            "Render (web service, plano free)",
            "render.yaml (IaC)",
            "Docker",
            "Docker Compose",
            "GitHub (auto-deploy em push para main)",
        ],
    ),
    (
        "Formatos e protocolos",
        [
            "JSON",
            "CSV",
            "SQL (dump)",
            "XLSX (Office Open XML)",
            "HTTP / HTTPS",
            "multipart/form-data",
            "TLS / SSL",
        ],
    ),
    (
        "Ferramentas de desenvolvimento",
        [
            "Git",
            "Bash / PowerShell",
            "venv",
            "pip",
        ],
    ),
]


def build() -> None:
    doc = SimpleDocTemplate(
        str(DESTINO),
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title="Backlog de Tecnologias — Grama Webcam",
        author="Grama Exato",
        subject="Stack tecnica do projeto Grama Webcam",
    )

    styles = getSampleStyleSheet()

    titulo = ParagraphStyle(
        "TituloProjeto",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=VERDE,
        spaceAfter=4,
        alignment=TA_LEFT,
    )
    subtitulo = ParagraphStyle(
        "Subtitulo",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        textColor=CINZA_CLARO,
        spaceAfter=24,
        alignment=TA_LEFT,
    )
    categoria = ParagraphStyle(
        "Categoria",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=VERDE,
        spaceBefore=14,
        spaceAfter=6,
        alignment=TA_LEFT,
        leftIndent=0,
        borderPadding=0,
    )
    item = ParagraphStyle(
        "Item",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        textColor=CINZA,
        leading=15,
        alignment=TA_LEFT,
    )
    rodape = ParagraphStyle(
        "Rodape",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        textColor=CINZA_CLARO,
        alignment=TA_LEFT,
    )

    story = [
        Paragraph("Backlog de Tecnologias", titulo),
        Paragraph("Projeto Grama Webcam &nbsp;&middot;&nbsp; Grama Exato", subtitulo),
    ]

    for nome_categoria, tecnologias in CATEGORIAS:
        story.append(Paragraph(nome_categoria, categoria))
        story.append(
            ListFlowable(
                [ListItem(Paragraph(tec, item), leftIndent=12) for tec in tecnologias],
                bulletType="bullet",
                start="•",
                bulletFontName="Helvetica",
                bulletFontSize=10,
                leftIndent=14,
                spaceBefore=0,
                spaceAfter=0,
            )
        )

    story.append(Spacer(1, 24))
    total = sum(len(tecs) for _, tecs in CATEGORIAS)
    story.append(
        Paragraph(
            f"{total} tecnologias em {len(CATEGORIAS)} categorias.",
            rodape,
        )
    )

    doc.build(story)
    print(f"OK: {DESTINO.relative_to(RAIZ)} gerado ({DESTINO.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
