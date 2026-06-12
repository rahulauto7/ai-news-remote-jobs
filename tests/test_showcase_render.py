"""Part 3: build_showcase renders two labeled sub-blocks, sorted by deadline.

Hackathons & Competitions (prize + deadline) and Accelerators & Incubators
(who-can-apply + what-you-get + deadline), each ordered by deadline ascending
with rolling/undated programs last.
"""

import os
import sys

from fpdf import FPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import generate_pdf as G


def _fresh_pdf():
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(G.MARGIN, G.MARGIN, G.MARGIN)
    G.register_fonts(pdf)
    return pdf


def test_fmt_deadline_formats_iso_and_rolling():
    assert G._fmt_deadline("2026-06-15") == "June 15, 2026"
    assert G._fmt_deadline("2026-06-05T09:00:00Z") == "June 5, 2026"  # single-digit day, no zero pad
    assert G._fmt_deadline(None) == "Rolling — apply anytime"
    assert G._fmt_deadline("") == "Rolling — apply anytime"


def test_build_showcase_runs_on_mixed_list(tmp_path):
    items = [
        {"group": "hackathon", "title": "AI Agents Hackathon",
         "prize_summary": "$10,000", "deadline_iso": "2026-06-20",
         "url": "https://example.com/hack"},
        {"group": "accelerator", "title": "Antler Residency (AI)",
         "eligibility": "Solo founders welcome — no co-founder needed.",
         "benefits": "Pre-seed cash, residency, mentorship.",
         "deadline_iso": None, "url": "https://www.antler.co/apply"},
        {"group": "hackathon", "title": "Rolling Build Challenge",
         "deadline_iso": None, "url": "https://example.com/rolling"},  # null deadline
    ]
    pdf = _fresh_pdf()
    G.build_showcase(pdf, "product_showcase_opportunities", items, 2)
    out = tmp_path / "showcase.pdf"
    pdf.output(str(out))
    assert out.stat().st_size > 1000


def test_build_showcase_orders_each_group_by_deadline_ascending(tmp_path, monkeypatch):
    items = [
        {"group": "hackathon", "title": "H later", "deadline_iso": "2026-07-01"},
        {"group": "hackathon", "title": "H rolling", "deadline_iso": None},
        {"group": "hackathon", "title": "H soon", "deadline_iso": "2026-06-10"},
        {"group": "accelerator", "title": "A rolling", "deadline_iso": None},
        {"group": "accelerator", "title": "A soon", "deadline_iso": "2026-06-25"},
    ]

    # Spy on the title renderer (size 11.5) to capture render order.
    real_wrapped = G.wrapped
    titles = []

    def spy(pdf, x, y, w, text, family, style, size, color, lh=4.6):
        if size == 11.5:
            titles.append(text)
        return real_wrapped(pdf, x, y, w, text, family, style, size, color, lh=lh)

    monkeypatch.setattr(G, "wrapped", spy)

    pdf = _fresh_pdf()
    G.build_showcase(pdf, "product_showcase_opportunities", items, 2)
    pdf.output(str(tmp_path / "ordered.pdf"))

    # Hackathons first (soon -> later -> rolling), then accelerators (soon -> rolling).
    assert titles == ["H soon", "H later", "H rolling", "A soon", "A rolling"]


def test_kv_skips_missing_value():
    """A null/empty field draws nothing (no 'Prize: None' line) and leaves y put;
    a real value advances y."""
    pdf = _fresh_pdf()
    pdf.add_page()
    y0 = 40.0
    assert G._kv(pdf, G.MARGIN, y0, G.CONTENT_W, "Prize", None) == y0
    assert G._kv(pdf, G.MARGIN, y0, G.CONTENT_W, "Prize", "") == y0
    assert G._kv(pdf, G.MARGIN, y0, G.CONTENT_W, "Prize", "$5,000") > y0


def test_build_showcase_handles_empty(tmp_path):
    pdf = _fresh_pdf()
    G.build_showcase(pdf, "product_showcase_opportunities", [], 2)
    out = tmp_path / "empty.pdf"
    pdf.output(str(out))
    assert out.stat().st_size > 500  # a page with the note, not a crash
