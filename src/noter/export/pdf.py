"""Rapport PDF (fpdf2, polices intégrées Helvetica/Courier)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from noter.models import Recording, Segment, Summary, format_timestamp


class _Doc(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self._doc_title = title

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 6, _safe(self._doc_title), align="L")
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, f"{self.page_no()} / {{nb}}", align="C")


def _safe(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def generate_pdf(output_path: Path, rec: Recording, summary: Summary, segments: list[Segment] | None = None) -> Path:
    pdf = _Doc(rec.display_title)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    w = pdf.w - 2 * pdf.l_margin

    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(w, 10, _safe(rec.display_title))
    pdf.ln(2)
    pdf.set_draw_color(20, 20, 20)
    pdf.set_line_width(0.8)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.l_margin + w, y)
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    meta = [f"Date : {rec.started_at:%d/%m/%Y %H:%M}", f"Duree : {rec.duration_text}", f"Langue : {(rec.language or '?').upper()}"]
    if rec.project:
        meta.append(f"Projet : {rec.project}")
    if rec.tags:
        meta.append("Tags : " + ", ".join(rec.tags))
    pdf.cell(0, 5, _safe("   |   ".join(meta)))
    pdf.ln(12)

    _tldr_block(pdf, summary.tldr, w)
    pdf.ln(8)

    if summary.key_points:
        _section(pdf, "POINTS CLES", w)
        for p in summary.key_points:
            _bullet(pdf, p, w)
        pdf.ln(6)
    if summary.decisions:
        _section(pdf, "DECISIONS", w)
        for d in summary.decisions:
            _bullet(pdf, d, w, bullet=">")
        pdf.ln(6)
    if summary.actions:
        _section(pdf, "ACTIONS", w)
        for a in summary.actions:
            _action(pdf, a.display, w, a.done)
        pdf.ln(6)

    if segments:
        pdf.add_page()
        _section(pdf, "TRANSCRIPT", w)
        pdf.ln(2)
        for s in segments:
            _transcript_line(pdf, format_timestamp(s.start), s.speaker or "", s.text, w)

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(0, 5, "Rapport genere par Noter", align="C")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path


def _tldr_block(pdf: FPDF, text: str, w: float):
    x, y0 = pdf.l_margin, pdf.get_y()
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.set_x(x + 10)
    pdf.multi_cell(w - 16, 7, _safe(text))
    h = pdf.get_y() + 4 - y0
    pdf.set_fill_color(245, 246, 248)
    pdf.rect(x, y0 - 2, w, h, "F")
    pdf.set_fill_color(20, 20, 20)
    pdf.rect(x, y0 - 2, 3, h, "F")
    pdf.set_xy(x + 10, y0 + 2)
    pdf.multi_cell(w - 16, 7, _safe(text))


def _section(pdf: FPDF, title: str, w: float):
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 8, title)
    pdf.ln(8)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(4)


def _bullet(pdf: FPDF, text: str, w: float, bullet: str = "-"):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.set_x(pdf.l_margin + 4)
    pdf.cell(6, 6, bullet)
    pdf.multi_cell(w - 14, 6, _safe(text))
    pdf.ln(1)


def _action(pdf: FPDF, text: str, w: float, done: bool):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    x, y = pdf.l_margin, pdf.get_y()
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.4)
    pdf.rect(x + 4, y + 1, 4, 4, "DF" if done else "D")
    pdf.set_x(x + 12)
    pdf.multi_cell(w - 16, 6, _safe(text))
    pdf.ln(2)


def _transcript_line(pdf: FPDF, time_str: str, speaker: str, text: str, w: float):
    if pdf.get_y() > pdf.h - 25:
        pdf.add_page()
    pdf.set_font("Courier", "", 7.5)
    pdf.set_text_color(170, 170, 170)
    pdf.set_x(pdf.l_margin)
    pdf.cell(18, 5, time_str)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(28, 5, _safe(speaker[:16]))
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(w - 46, 5, _safe(text))
    pdf.ln(0.5)
