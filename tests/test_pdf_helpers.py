from fpdf import FPDF

from tools import generate_pdf as G


# ── Pure helpers ──────────────────────────────────────────────────────────────
def test_pick_highlight_word_skips_stopwords():
    assert G.pick_highlight_word("AI's godfather just sounded the alarm") == "godfather"


def test_pick_highlight_word_handles_empty():
    assert G.pick_highlight_word("") == ""


def test_stars_clamps():
    G.FONTS_OK = True  # ensure unicode star path for the assertion
    assert G.stars_str(5) == "★★★★★"
    assert G.stars_str(0) == "☆☆☆☆☆"
    assert G.stars_str(99) == "★★★★★"
    assert G.stars_str(None) == "☆☆☆☆☆"


def test_clean_strips_html_and_smart_quotes():
    G.FONTS_OK = True
    out = G.clean("<p>He said &ldquo;hi&rdquo; — really</p>")
    assert "<" not in out and "—" not in out
    assert out == 'He said "hi" - really'


def _fresh_pdf():
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(G.MARGIN, G.MARGIN, G.MARGIN)
    G.register_fonts(pdf)
    return pdf


# ── Render smoke tests ────────────────────────────────────────────────────────
def test_primitives_render_without_error(tmp_path):
    pdf = _fresh_pdf()
    pdf.add_page()
    G.dark_page(pdf)
    G.eyebrow(pdf, G.MARGIN, 20, "01 . REMOTE AI JOBS")
    y = G.highlight_headline(pdf, G.MARGIN, 40, "AI's godfather sounded the alarm",
                             size=22, ink=G.WHITE)
    y = G.card_box(pdf, G.MARGIN, y + 4, G.CONTENT_W,
                   "Quick take body text that wraps across multiple lines. " * 4,
                   label="Quick Take")
    y = G.callout(pdf, G.MARGIN, y + 4, G.CONTENT_W, "THE BIG PICTURE",
                  "Callout body. " * 20)
    G.tick_list(pdf, G.MARGIN, y + 4, G.CONTENT_W, ["beat one", "beat two", "beat three"])
    out = tmp_path / "smoke.pdf"
    pdf.output(str(out))
    assert out.stat().st_size > 1000


def test_pick_cover_story_returns_title(sample_doc):
    title, standfirst = G.pick_cover_story(sample_doc["sections"])
    assert isinstance(title, str) and title


def test_build_section_renders(sample_doc, tmp_path):
    pdf = _fresh_pdf()
    G.build_section(pdf, "global_ai_news", sample_doc["sections"].get("global_ai_news", []), 14)
    out = tmp_path / "sec.pdf"
    pdf.output(str(out))
    assert out.stat().st_size > 1000


def test_empty_section_renders_note(tmp_path):
    pdf = _fresh_pdf()
    G.build_section(pdf, "quantum_ai_research", [], 6)
    out = tmp_path / "empty.pdf"
    pdf.output(str(out))
    assert out.stat().st_size > 500  # a page with the note, not a crash


def test_specials_render(sample_doc, tmp_path):
    secs = sample_doc["sections"]
    cases = [
        (G.build_jobs, "remote_jobs"),
        (G.build_benchmark_table, "ai_model_benchmarks"),
        (G.build_viral_video, "viral_video_landscape"),
        (G.build_instagram_reels, "instagram_viral_reels"),
    ]
    for fn, key in cases:
        pdf = _fresh_pdf()
        fn(pdf, key, secs.get(key, []), 1)
        out = tmp_path / f"{key}.pdf"
        pdf.output(str(out))
        assert out.stat().st_size > 1000, key


def test_full_generate_pdf(monkeypatch, tmp_path, sample_doc):
    out = tmp_path / "daily.pdf"
    monkeypatch.setattr(G, "OUTPUT_FILE", str(out))
    ok, path = G.generate_pdf()
    assert ok and out.stat().st_size > 5000
    data = out.read_bytes()
    pages = data.count(b"/Type /Page") + data.count(b"/Type/Page")
    # cover + contents + 19 sections + closing, some sections span pages
    assert pages >= 22, f"only {pages} pages"
