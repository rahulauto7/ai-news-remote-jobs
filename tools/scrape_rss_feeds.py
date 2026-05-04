"""
Scrape RSS feeds from 25+ AI news sources.
Filters to last 24 hours. Outputs .tmp/rss_articles.json
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "rss_articles.json")

# ── RSS Feed Sources ──────────────────────────────────────────────────────────
# Organized by category for easy maintenance
FEEDS = {
    # General AI News
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Ars Technica AI": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "The Decoder": "https://the-decoder.com/feed/",
    "AI News": "https://www.artificialintelligence-news.com/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
    "ZDNet AI": "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
    "The Register AI": "https://www.theregister.com/software/ai_ml/headlines.atom",

    # Company Blogs
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",

    # Indian AI Sources
    "Inc42": "https://inc42.com/feed/",
    "YourStory": "https://yourstory.com/feed",
    "Economic Times Tech": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",

    # Quantum Computing + AI
    "arXiv Quantum Physics": "https://rss.arxiv.org/rss/quant-ph",
    "arXiv AI": "https://rss.arxiv.org/rss/cs.AI",
    "arXiv Machine Learning": "https://rss.arxiv.org/rss/cs.LG",

    # Music Industry / Copyright
    "Music Business Worldwide": "https://www.musicbusinessworldwide.com/feed/",
    "Digital Music News": "https://www.digitalmusicnews.com/feed/",
    "Hypebot": "https://www.hypebot.com/feed",

    # Anthropic / Claude
    "Anthropic Blog": "https://www.anthropic.com/rss.xml",

    # xAI / Elon Musk AI
    "xAI Blog": "https://x.ai/blog/rss.xml",
    # Elon Musk posts on x.com — direct scraping requires auth (402), so we
    # proxy via Google News RSS filtered to site:x.com/elonmusk
    "Elon Musk on X (via Google News)": "https://news.google.com/rss/search?q=%22elon+musk%22+(xAI+OR+Grok+OR+AI)+site:x.com%2Felonmusk&hl=en-US&gl=US&ceid=US:en",

    # AI Tools & Business
    "Product Hunt AI": "https://www.producthunt.com/feed?category=artificial-intelligence",
    "Futurism": "https://futurism.com/feed",

    # General News (non-AI) — world + India top headlines
    "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "The Hindu - National": "https://www.thehindu.com/news/national/feeder/default.rss",
    "NDTV Top Stories": "https://feeds.feedburner.com/ndtvnews-top-stories",
}


# arXiv feeds return hundreds of papers — limit to most relevant
ARXIV_MAX_PER_FEED = 15

def fetch_feed(name, url, cutoff_time, timeout=15):
    """Fetch and parse a single RSS feed. Returns list of articles."""
    is_arxiv = name.startswith("arXiv")
    articles = []
    try:
        response = requests.get(url, timeout=timeout, headers={
            "User-Agent": "GlobalAINews/1.0 (RSS Reader)"
        })
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        for entry in feed.entries:
            # Parse published date
            published = None
            for date_field in ("published_parsed", "updated_parsed", "created_parsed"):
                parsed_time = getattr(entry, date_field, None)
                if parsed_time:
                    published = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                    break

            # If no date found, include it anyway (better to over-include)
            if published and published < cutoff_time:
                continue

            article = {
                "title": getattr(entry, "title", "No title"),
                "url": getattr(entry, "link", ""),
                "source": name,
                "published": published.isoformat() if published else None,
                "summary": getattr(entry, "summary", getattr(entry, "description", ""))[:500],
                "category": _categorize_source(name),
            }
            articles.append(article)

            # Cap arXiv to avoid flooding with hundreds of papers
            if is_arxiv and len(articles) >= ARXIV_MAX_PER_FEED:
                break

    except requests.exceptions.Timeout:
        print(f"  [TIMEOUT] {name} ({url})")
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] {name}: {e}")
    except Exception as e:
        print(f"  [PARSE ERROR] {name}: {e}")

    return articles


def _categorize_source(source_name):
    """Map source to broad category for initial sorting."""
    categories = {
        "indian": ["Inc42", "YourStory", "Economic Times Tech"],
        "quantum": ["arXiv Quantum Physics"],
        "ai_research": ["arXiv AI", "arXiv Machine Learning"],
        "music_copyright": ["Music Business Worldwide", "Digital Music News", "Hypebot"],
        "tools": ["Product Hunt AI"],
        "company_blog": ["OpenAI Blog", "Google AI Blog", "Hugging Face Blog"],
        "anthropic_claude": ["Anthropic Blog"],
        "elon_xai": ["xAI Blog"],
        "general_news": ["BBC World", "The Hindu - National", "NDTV Top Stories"],
    }
    for cat, sources in categories.items():
        if source_name in sources:
            return cat
    return "general"


def scrape_all_feeds():
    """Scrape all RSS feeds and save to JSON."""
    os.makedirs(TMP_DIR, exist_ok=True)

    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
    all_articles = []

    print(f"Scraping {len(FEEDS)} RSS feeds (cutoff: {cutoff_time.strftime('%Y-%m-%d %H:%M UTC')})...")

    for name, url in FEEDS.items():
        articles = fetch_feed(name, url, cutoff_time)
        print(f"  [{len(articles):>3} articles] {name}")
        all_articles.extend(articles)
        time.sleep(0.5)  # polite delay

    # Deduplicate by URL
    seen_urls = set()
    unique_articles = []
    for article in all_articles:
        if article["url"] and article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    # Sort by date (newest first)
    unique_articles.sort(
        key=lambda a: a.get("published") or "1970-01-01",
        reverse=True
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "cutoff": cutoff_time.isoformat(),
            "total_articles": len(unique_articles),
            "sources_scraped": len(FEEDS),
            "articles": unique_articles,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nDone! {len(unique_articles)} unique articles saved to {OUTPUT_FILE}")
    return unique_articles


if __name__ == "__main__":
    scrape_all_feeds()
