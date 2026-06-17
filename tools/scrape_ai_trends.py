"""
"What People in AI Are Searching For" — aggregates trending AI topics from
three free sources:

  - Google Trends (pytrends): rising + top related queries for AI seed terms,
    global + India.
  - Hacker News (Algolia API): top AI/LLM/agent stories in the last 24h.
  - Reddit (PRAW, read-only OAuth): hot threads in r/MachineLearning,
    r/LocalLLaMA, r/singularity, r/ArtificialIntelligence, r/OpenAI,
    r/Anthropic over the last 24h.

Each source contributes "signals". The aggregator buckets signals by a
normalized topic key (lowercase, stop-words stripped) and scores each topic
by combined signal strength. A prefer-fresh rotation pass (namespace "trends"
in data/content_seen.json, TREND_COOLDOWN_DAYS window) then fills the top 20
from topics not shown in the last 2 days first, falling back to repeats only
if there aren't enough fresh ones — so a topic that's merely still trending
isn't dropped, but it stops crowding out fresher ones. Output: .tmp/ai_trends.json
with the top 20 topics, sample URLs per topic, and a `sources` tag list per topic.

Env vars (optional — each source degrades gracefully if missing or fails):
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT

Google Trends + HN Algolia need no keys.

Run standalone:
    python -m tools.scrape_ai_trends
"""

import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "ai_trends.json")

sys.path.insert(0, PROJECT_ROOT)
from tools import content_history

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Namespace + cooldown for cross-day topic rotation (see aggregate_topics /
# run()). Shorter than the 7-day news dedup window because trending topics are
# expected to legitimately persist longer than news articles — this only
# de-prioritizes repeats in favor of fresher ones, it never hard-drops a topic
# that's still genuinely the only thing trending.
TRENDS_NS = "trends"
TREND_COOLDOWN_DAYS = 3

USER_AGENT = "Mozilla/5.0 (compatible; ai-news-trends-bot/1.0)"

# Seed terms fed to Google Trends for related-query expansion.
GOOGLE_TRENDS_SEEDS = [
    "AI", "AI agents", "AI automation", "LLM", "ChatGPT", "Claude", "generative AI",
]

# Subreddits to pull hot threads from. Each has high AI signal density.
AI_SUBREDDITS = [
    "MachineLearning", "LocalLLaMA", "singularity", "ArtificialIntelligence",
    "OpenAI", "Anthropic", "ClaudeAI", "AI_Agents",
]

# English stop-words stripped during topic normalization.
STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "with",
    "is", "are", "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "as", "by", "from", "it", "its", "i", "you", "we", "they", "he",
    "she", "what", "how", "why", "when", "which", "who", "whom",
    "new", "best", "top", "via", "vs", "over", "ai", "llm",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]+")
_HTTP_TIMEOUT = 20


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _normalize_topic(text: str) -> str:
    """Lowercase + strip URLs + drop stop-words + collapse whitespace.

    The aggregator clusters by exact normalized string match, so this is the
    canonical key. Keep it conservative — we want 'Claude Code agents' and
    'claude code agents' to collapse, but not 'Claude' and 'Claude Code'.
    """
    if not text:
        return ""
    s = text.lower()
    s = re.sub(r"https?://\S+", "", s)
    tokens = [t for t in _TOKEN_RE.findall(s) if t not in STOP_WORDS]
    return " ".join(tokens[:8])  # cap at 8 meaningful tokens


# ── Google Trends ────────────────────────────────────────────────────────────
def _patch_urllib3_for_pytrends() -> None:
    """pytrends 4.9.2 passes the old `method_whitelist` kwarg to urllib3's Retry,
    which urllib3 v2 renamed to `allowed_methods` — so `TrendReq()` crashes with
    `__init__() got an unexpected keyword argument 'method_whitelist'`. Translate
    the kwarg at the Retry level so pytrends keeps working on urllib3 v2.
    Idempotent + best-effort (no-op if urllib3 internals change)."""
    try:
        import urllib3.util.retry as _retry
    except Exception:
        return
    if getattr(_retry.Retry, "_pytrends_compat", False):
        return
    _orig_init = _retry.Retry.__init__

    def _init(self, *args, **kwargs):
        if "method_whitelist" in kwargs:
            kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
        # Google answers trends 429s with Retry-After in the tens of minutes;
        # sleeping on it once per batch turned a 5-min step into an hour.
        kwargs.setdefault("respect_retry_after_header", False)
        return _orig_init(self, *args, **kwargs)

    _retry.Retry.__init__ = _init
    _retry.Retry._pytrends_compat = True
    if not hasattr(_retry.Retry, "DEFAULT_METHOD_WHITELIST") and hasattr(
        _retry.Retry, "DEFAULT_ALLOWED_METHODS"
    ):
        _retry.Retry.DEFAULT_METHOD_WHITELIST = _retry.Retry.DEFAULT_ALLOWED_METHODS


def fetch_google_trends() -> list[dict]:
    """Use pytrends to get rising + top related queries for AI seed terms.

    Returns list of {topic, score, source, geo, sample_url} dicts.
    Degrades to [] if pytrends isn't installed or the service rate-limits us.
    """
    signals: list[dict] = []
    try:
        from pytrends.request import TrendReq
    except ImportError:
        _log("[google_trends] pytrends not installed - skipping (pip install pytrends)")
        return signals

    _patch_urllib3_for_pytrends()

    budget = float(os.environ.get("TRENDS_BUDGET_SECONDS", "300"))
    deadline = time.time() + budget

    for geo_code, geo_label in [("", "global"), ("IN", "india")]:
        if time.time() > deadline:
            _log(f"[google_trends] budget {budget:.0f}s exhausted - skipping {geo_label}")
            break
        try:
            pytrends = TrendReq(
                hl="en-US", tz=330, retries=2, backoff_factor=0.5,
                timeout=(10, 25),  # default (2,5) read-timeouts often on trends.google.com
            )
            # pytrends caps payload at 5 keywords; batch the seeds.
            for batch_start in range(0, len(GOOGLE_TRENDS_SEEDS), 5):
                if time.time() > deadline:
                    _log(f"[google_trends:{geo_label}] budget {budget:.0f}s exhausted - stopping early")
                    break
                batch = GOOGLE_TRENDS_SEEDS[batch_start:batch_start + 5]
                # Try 1-day for truly fresh daily signal; fall back to 4-hour if empty.
                related = {}
                for tf in ("now 1-d", "now 4-H"):
                    pytrends.build_payload(kw_list=batch, timeframe=tf, geo=geo_code)
                    try:
                        _related = pytrends.related_queries() or {}
                    except Exception as e:
                        _log(f"[google_trends:{geo_label}] related_queries failed batch {batch_start} tf={tf}: {e}")
                        _related = {}
                    has_data = any(
                        isinstance(v, dict) and (
                            (v.get("rising") is not None and not v["rising"].empty) or
                            (v.get("top") is not None and not v["top"].empty)
                        )
                        for v in _related.values()
                    )
                    if has_data:
                        related = _related
                        break
                    _log(f"[google_trends:{geo_label}] no data for tf={tf} batch {batch_start}, trying fallback")
                if not related:
                    continue

                for seed, blocks in related.items():
                    if not isinstance(blocks, dict):
                        continue
                    # Rising queries — surging right now (the user cares most about these).
                    rising = blocks.get("rising")
                    if rising is not None and not rising.empty:
                        for _, row in rising.head(10).iterrows():
                            q = str(row.get("query", "")).strip()
                            value = float(row.get("value", 0) or 0)
                            if not q:
                                continue
                            signals.append({
                                "topic": q,
                                "raw_score": value,
                                "source": "google_trends_rising",
                                "geo": geo_label,
                                "sample_url": (
                                    f"https://trends.google.com/trends/explore?"
                                    f"q={quote_plus(q)}&date=now+1-d"
                                    + (f"&geo={geo_code}" if geo_code else "")
                                ),
                            })

                    # Top queries — durably high interest.
                    top = blocks.get("top")
                    if top is not None and not top.empty:
                        for _, row in top.head(5).iterrows():
                            q = str(row.get("query", "")).strip()
                            value = float(row.get("value", 0) or 0)
                            if not q:
                                continue
                            signals.append({
                                "topic": q,
                                "raw_score": value,
                                "source": "google_trends_top",
                                "geo": geo_label,
                                "sample_url": (
                                    f"https://trends.google.com/trends/explore?"
                                    f"q={quote_plus(q)}&date=now+1-d"
                                    + (f"&geo={geo_code}" if geo_code else "")
                                ),
                            })
                time.sleep(1.5)  # pytrends rate-limit guard
        except Exception as e:
            _log(f"[google_trends:{geo_label}] error: {e}")
            continue

    _log(f"[google_trends] {len(signals)} signals")
    return signals


# ── Hacker News (Algolia) ────────────────────────────────────────────────────
def fetch_hn_ai() -> list[dict]:
    """Top AI/LLM/agent stories on HN in the last 24h, sorted by points."""
    signals: list[dict] = []
    now_unix = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_unix - 24 * 3600
    queries = ["AI", "LLM", "agent", "Claude", "ChatGPT", "OpenAI", "Anthropic"]
    seen_ids: set[str] = set()
    for q in queries:
        try:
            url = (
                "https://hn.algolia.com/api/v1/search"
                f"?query={quote_plus(q)}&tags=story"
                f"&numericFilters=created_at_i>{cutoff}"
                "&hitsPerPage=20"
            )
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                _log(f"[hn:{q}] HTTP {r.status_code}")
                continue
            for h in r.json().get("hits", []):
                obj_id = h.get("objectID")
                if not obj_id or obj_id in seen_ids:
                    continue
                seen_ids.add(obj_id)
                title = (h.get("title") or "").strip()
                if not title:
                    continue
                story_url = h.get("url") or f"https://news.ycombinator.com/item?id={obj_id}"
                points = int(h.get("points") or 0)
                comments = int(h.get("num_comments") or 0)
                signals.append({
                    "topic": title,
                    "raw_score": points + 0.3 * comments,
                    "source": "hn",
                    "geo": "global",
                    "sample_url": story_url,
                })
            time.sleep(0.3)
        except Exception as e:
            _log(f"[hn:{q}] error: {e}")
            continue

    _log(f"[hn] {len(signals)} signals")
    return signals


# ── Reddit ───────────────────────────────────────────────────────────────────
def fetch_reddit_ai() -> list[dict]:
    """Hot threads from AI subreddits in the last 24h."""
    signals: list[dict] = []
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = os.environ.get("REDDIT_USER_AGENT", "ai-news-trends-bot/1.0").strip()

    # PRAW path (preferred): authenticated, higher rate limit.
    if client_id and client_secret:
        try:
            import praw
            reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
            )
            reddit.read_only = True
            cutoff = datetime.now(timezone.utc).timestamp() - 24 * 3600
            for sub in AI_SUBREDDITS:
                try:
                    for post in reddit.subreddit(sub).hot(limit=25):
                        if post.created_utc < cutoff:
                            continue
                        if post.stickied:
                            continue
                        title = (post.title or "").strip()
                        if not title:
                            continue
                        signals.append({
                            "topic": title,
                            "raw_score": float(post.score or 0) + 0.5 * float(post.num_comments or 0),
                            "source": f"reddit:r/{sub}",
                            "geo": "global",
                            "sample_url": f"https://www.reddit.com{post.permalink}",
                        })
                except Exception as e:
                    _log(f"[reddit:{sub}] error: {e}")
                    continue
            _log(f"[reddit:praw] {len(signals)} signals")
            return signals
        except ImportError:
            _log("[reddit] praw not installed - falling back to anonymous JSON endpoint")
        except Exception as e:
            _log(f"[reddit:praw] init error: {e} - falling back to JSON endpoint")

    # Anonymous JSON fallback. Lower rate limit, no auth. Reddit blocks generic
    # bot UAs (HTTP 403) — use their documented UA format to maximise success
    # on non-blocked IPs. Datacenter IPs may still 403; the section then ships
    # from HN + Google Trends alone (Reddit is supplementary, not required).
    anon_ua = "python:ai-news-trends:v1.0 (by /u/rahulmeenaailead)"
    reddit_403 = 0
    for sub in AI_SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25&raw_json=1"
            r = requests.get(
                url,
                headers={"User-Agent": anon_ua, "Accept": "application/json"},
                timeout=_HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                if r.status_code == 403:
                    reddit_403 += 1
                _log(f"[reddit:{sub}] HTTP {r.status_code}")
                continue
            cutoff = datetime.now(timezone.utc).timestamp() - 24 * 3600
            for child in r.json().get("data", {}).get("children", []):
                d = child.get("data", {})
                if d.get("stickied"):
                    continue
                created = float(d.get("created_utc") or 0)
                if created < cutoff:
                    continue
                title = (d.get("title") or "").strip()
                if not title:
                    continue
                signals.append({
                    "topic": title,
                    "raw_score": float(d.get("score") or 0) + 0.5 * float(d.get("num_comments") or 0),
                    "source": f"reddit:r/{sub}",
                    "geo": "global",
                    "sample_url": f"https://www.reddit.com{d.get('permalink', '')}",
                })
            time.sleep(1.0)
        except Exception as e:
            _log(f"[reddit:{sub}] error: {e}")
            continue

    if reddit_403 and not signals:
        _log(
            "[reddit:anon] all subreddits returned 403 (IP-level block). "
            "Set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET for the authenticated PRAW path."
        )
    _log(f"[reddit:anon] {len(signals)} signals")
    return signals


# ── Aggregation ──────────────────────────────────────────────────────────────
def aggregate_topics(signals: list[dict], top_n: int = 40) -> list[dict]:
    """Cluster signals by normalized topic key. Score = sum of log-scaled signals.

    Returns a candidate pool larger than the final section size (default 40,
    vs. the 20 actually shown) so run() can apply prefer-fresh rotation before
    slicing down to the top 20."""
    buckets: dict[str, dict] = {}
    for sig in signals:
        topic_raw = (sig.get("topic") or "").strip()
        key = _normalize_topic(topic_raw)
        if not key or len(key) < 4:
            continue
        b = buckets.setdefault(key, {
            "topic": topic_raw[:140],
            "score": 0.0,
            "sources": set(),
            "geos": set(),
            "sample_urls": [],
            "_url_set": set(),
        })
        # Log-scale to dampen runaway scores (HN can hit 1000+ points; one viral
        # topic shouldn't drown out the long tail).
        b["score"] += math.log1p(max(0.0, float(sig.get("raw_score", 0))))
        b["sources"].add(sig.get("source", ""))
        b["geos"].add(sig.get("geo", ""))
        url = sig.get("sample_url", "")
        if url and url not in b["_url_set"] and len(b["sample_urls"]) < 3:
            b["sample_urls"].append(url)
            b["_url_set"].add(url)
        # Keep the longer/cleaner topic phrase if we see one.
        if len(topic_raw) > len(b["topic"]) and len(topic_raw) < 140:
            b["topic"] = topic_raw

    flat = []
    for key, b in buckets.items():
        flat.append({
            "topic": b["topic"],
            "norm_key": key,
            "score": round(b["score"], 2),
            "sources": sorted(s for s in b["sources"] if s),
            "geos": sorted(g for g in b["geos"] if g),
            "sample_urls": b["sample_urls"],
            "signal_count": len([s for s in signals if _normalize_topic(s.get("topic", "")) == key]),
        })
    flat.sort(key=lambda t: -t["score"])
    return flat[:top_n]


def run() -> bool:
    os.makedirs(TMP_DIR, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    signals: list[dict] = []
    signals.extend(fetch_google_trends())
    signals.extend(fetch_hn_ai())
    signals.extend(fetch_reddit_ai())

    candidates = aggregate_topics(signals)

    # Prefer-fresh rotation: fill the top 20 from topics not recently shown
    # first, only falling back to repeats when there aren't enough fresh ones
    # to fill the section (mirrors the viral video/reel "widen-then-note"
    # dedup pattern used elsewhere in this pipeline).
    seen = content_history.recently_seen(TRENDS_NS, TREND_COOLDOWN_DAYS)
    fresh = [t for t in candidates if t["norm_key"] not in seen]
    repeat = [t for t in candidates if t["norm_key"] in seen]
    topics = (fresh + repeat)[:20]
    content_history.record_shown(TRENDS_NS, [t["norm_key"] for t in topics])

    payload = {
        "generated_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "raw_signal_count": len(signals),
        "topic_count": len(topics),
        "topics": topics,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    _log(f"[ai_trends] wrote {len(topics)} topics (from {len(signals)} signals) -> {OUTPUT_FILE}")
    return True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
