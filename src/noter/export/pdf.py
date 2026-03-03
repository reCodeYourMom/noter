"""Génération de rapports PDF premium pour les enregistrements."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


class NoterPDF(FPDF):
    """PDF avec header/footer custom."""

    def __init__(self, title: str):
        super().__init__()
        self._doc_title = title

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 6, self._doc_title, align="L")
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, f"{self.page_no()} / {{nb}}", align="C")


def _safe(text: str) -> str:
    """Nettoie le texte pour fpdf2 (latin-1 safe)."""
    return text.encode("latin-1", "replace").decode("latin-1")


def generate_pdf(
    output_path: Path,
    title: str,
    date_str: str,
    duration_str: str,
    language: str,
    tldr: str,
    key_points: list[str],
    decisions: list[str],
    actions: list[str],
    transcript: str,
) -> Path:
    """Génère un rapport PDF premium."""
    pdf = NoterPDF(title)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    W = pdf.w - 2 * pdf.l_margin

    # ─── Titre ────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(W, 11, _safe(title))
    pdf.ln(2)

    # Ligne épaisse
    pdf.set_draw_color(20, 20, 20)
    pdf.set_line_width(0.8)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.l_margin + W, y)
    pdf.ln(6)

    # Métadonnées
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    meta = "   |   ".join(filter(None, [
        f"Date : {date_str}" if date_str else "",
        f"Duree : {duration_str}" if duration_str else "",
        f"Langue : {language}" if language else "",
    ]))
    pdf.cell(0, 5, _safe(meta))
    pdf.ln(12)

    # ─── TL;DR ────────────────────────────────────────────
    _tldr_block(pdf, tldr, W)
    pdf.ln(8)

    # ─── Sections ─────────────────────────────────────────
    if key_points:
        _section_title(pdf, "POINTS CLES", W)
        for p in key_points:
            _bullet(pdf, p, W)
        pdf.ln(6)

    if decisions:
        _section_title(pdf, "DECISIONS", W)
        for d in decisions:
            _bullet(pdf, d, W, bullet=">")
        pdf.ln(6)

    if actions:
        _section_title(pdf, "ACTIONS", W)
        for a in actions:
            _action_item(pdf, a, W)
        pdf.ln(6)

    # ─── Transcript ───────────────────────────────────────
    if transcript and transcript.strip():
        pdf.add_page()
        _section_title(pdf, "TRANSCRIPT", W)
        pdf.ln(2)
        for line in transcript.strip().split("\n"):
            _transcript_line(pdf, line, W)

    # ─── Branding ─────────────────────────────────────────
    pdf.ln(10)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + W, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(0, 5, "Rapport genere par Noter", align="C")

    pdf.output(str(output_path))
    return output_path


def _tldr_block(pdf: FPDF, tldr: str, w: float):
    """Bloc TL;DR avec fond gris et barre gauche noire."""
    x = pdf.l_margin
    y_start = pdf.get_y()

    # Écrire le texte d'abord pour mesurer la hauteur
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.set_x(x + 10)
    pdf.multi_cell(w - 16, 7, _safe(tldr))
    y_end = pdf.get_y() + 4

    block_h = y_end - y_start

    # Dessiner le fond par-dessous (revenir en arrière)
    pdf.set_fill_color(245, 246, 248)
    pdf.rect(x, y_start - 2, w, block_h, "F")

    # Barre gauche noire
    pdf.set_fill_color(20, 20, 20)
    pdf.rect(x, y_start - 2, 3, block_h, "F")

    # Réécrire le texte par-dessus le fond
    pdf.set_y(y_start + 2)
    pdf.set_x(x + 10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(w - 16, 7, _safe(tldr))


def _section_title(pdf: FPDF, title: str, w: float):
    """Titre de section uppercase avec ligne."""
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 8, title)
    pdf.ln(8)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(4)


def _bullet(pdf: FPDF, text: str, w: float, bullet: str = "-"):
    """Bullet point."""
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    x = pdf.get_x()
    pdf.set_x(x + 4)
    pdf.cell(6, 6, bullet)
    pdf.multi_cell(w - 14, 6, _safe(text))
    pdf.ln(1)


def _action_item(pdf: FPDF, text: str, w: float):
    """Action item avec checkbox."""
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    x = pdf.get_x()
    y = pdf.get_y()

    # Checkbox dessinée
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.4)
    pdf.rect(x + 4, y + 1, 4, 4)

    pdf.set_x(x + 12)
    pdf.multi_cell(w - 16, 6, _safe(text))

    # Séparation légère
    pdf.set_draw_color(240, 240, 240)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin + 4, pdf.get_y() + 1, pdf.l_margin + w - 4, pdf.get_y() + 1)
    pdf.ln(3)


def _transcript_line(pdf: FPDF, line: str, w: float):
    """Une ligne de transcript."""
    if not line.strip():
        return

    time_str = ""
    speaker = ""
    text = line

    if line.startswith("[") and "] " in line:
        time_str = line[1:line.index("]")]
        rest = line[line.index("] ") + 2:]
        if ": " in rest:
            speaker, text = rest.split(": ", 1)
        else:
            text = rest

    if pdf.get_y() > pdf.h - 25:
        pdf.add_page()

    x = pdf.l_margin

    # Time
    pdf.set_font("Courier", "", 7.5)
    pdf.set_text_color(170, 170, 170)
    pdf.set_xy(x, pdf.get_y())
    pdf.cell(18, 5, time_str)

    # Speaker
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(28, 5, _safe(speaker))

    # Text
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(w - 46, 5, _safe(text))
    pdf.ln(0.5)
