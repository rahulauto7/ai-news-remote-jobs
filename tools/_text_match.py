"""
Shared text-matching primitives used across multiple scrapers/scoring modules.

Extracted from tools/scrape_hackathons.py so jobs (tools/job_match.py),
hackathons (tools/scrape_hackathons.py), and Instagram-reel discovery
(tools/scrape_instagram_reels.py) share one source of truth.

Provides:
  - AI_KEYWORDS_WORD / AI_KEYWORDS_PHRASE  (the canonical AI vocabulary)
  - matches_ai(text)                       (word-boundary aware AI gate)
  - tokenize_words(text)                   (lowercase word-boundary tokens)
  - extract_skill_hits(text, skills, weights=None)
        Returns the subset of skills (lowercase) present in `text` plus
        their summed weights. Used by job_match.score_job() and any other
        skill-matching code.

Word-boundary matching avoids false positives like "fair", "available",
"captain", "airbnb" that bit the hackathon scraper when it used substring
matching.
"""

from __future__ import annotations

import re

# Canonical AI keyword set. Bias to false positives within the AI domain.
AI_KEYWORDS_WORD = {
    "ai", "ml", "llm", "llms", "agent", "agents", "agentic", "nlp",
    "genai", "generative", "rag", "multimodal", "diffusion", "transformer",
    "transformers", "neural", "automation", "robotics", "autonomous",
    "openai", "anthropic", "claude", "mistral", "gemini", "llama",
    "perplexity", "huggingface", "deepseek", "qwen", "groq", "bedrock",
}

AI_KEYWORDS_PHRASE = [
    "a.i.", "machine learning", "deep learning", "computer vision",
    "foundation model", "voice ai", "music ai", "stable diffusion",
    "hugging face", "vision language", "speech to text", "text to speech",
    "synthetic data", "self-driving", "ai agent", "ai model",
]


_WORD_RE = re.compile(r"[A-Za-z0-9.]+")


def tokenize_words(text: str) -> set[str]:
    """Lowercase word-boundary tokens from `text`."""
    if not text:
        return set()
    return set(_WORD_RE.findall(text.lower()))


def matches_ai(text: str) -> bool:
    """True if any AI keyword (phrase or word-boundary) appears in text."""
    if not text:
        return False
    t = text.lower()
    if any(p in t for p in AI_KEYWORDS_PHRASE):
        return True
    return bool(tokenize_words(t) & AI_KEYWORDS_WORD)


def extract_skill_hits(text: str, skills, weights: dict | None = None):
    """Return (matched_skills_list, total_weight) for skill terms found in text.

    `skills` may be a flat iterable of skill terms (lowercase) or a dict
    mapping `term -> weight`. If `weights` is provided, it overrides per-term
    weights from a `skills` dict.

    Multi-word skill terms (e.g. "ai automation", "claude code") are matched
    as substrings; single-word terms are matched on word boundaries.
    """
    if not text:
        return [], 0
    t = text.lower()
    tokens = tokenize_words(t)

    if isinstance(skills, dict):
        items = list(skills.items())
    else:
        items = [(s, 1) for s in skills]
    if weights:
        items = [(term, weights.get(term, w)) for term, w in items]

    hits = []
    total = 0
    for term, w in items:
        term_l = term.lower().strip()
        if not term_l:
            continue
        if " " in term_l or "-" in term_l or "." in term_l:
            # Phrase / hyphenated / dotted term: substring match.
            if term_l in t:
                hits.append(term_l)
                total += w
        else:
            # Single-word term: word-boundary match.
            if term_l in tokens:
                hits.append(term_l)
                total += w
    return hits, total
