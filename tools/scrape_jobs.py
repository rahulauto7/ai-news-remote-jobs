"""
Scrape worldwide-remote, entry-level AI jobs from multiple sources.

Targeting:
  * worldwide-remote only (no US-only / country-locked "remote" listings)
  * AI-only (KEYWORDS gate + per-source keyword filter)
  * entry-level / junior (no senior / lead / principal / 5+yrs)
  * any employment type (full-time, part-time, contract, freelance, intern)

Filtering happens in two layers:
  1. per-source location + keyword gates (Greenhouse, Lever, Ashby, etc.)
  2. post-scrape `is_worldwide_remote` + `is_entry_level` pass in
     `scrape_all_jobs()` for boards that don't surface location cleanly.

Reliable sources (work from datacenter IPs — used in cloud routine):
  Remotive, RemoteOK, We Work Remotely (RSS), Himalayas, Hacker News (Algolia),
  Greenhouse public boards, Lever public boards, Ashby public boards.

Fragile sources (block datacenter IPs with 403/CAPTCHA — opt-in via env):
  LinkedIn, Wellfound, Indeed, X/Twitter.
  Skipped by default. Set JOBS_FRAGILE_SOURCES=1 to enable (works on a
  residential IP, e.g. local laptop).

Outputs: .tmp/jobs.json + .tmp/jobs.csv. Always writes a valid JSON file even
if every source fails so the downstream pipeline never blocks on missing data.

Each source is independent — failures in one don't kill the others.
"""

import csv
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

INCLUDE_FRAGILE = os.environ.get("JOBS_FRAGILE_SOURCES", "0").strip() == "1"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
JOBS_JSON = os.path.join(TMP_DIR, "jobs.json")
JOBS_CSV = os.path.join(TMP_DIR, "jobs.csv")

# Search terms driving every keyword-based source. Expanded from 8 -> 19, derived
# from workflows/user_profile.md (target roles + top-weighted skills) so the daily
# candidate pool is deep enough to surface DIFFERENT roles each day instead of
# recycling the same handful after cross-run dedup. job_match.py re-ranks the wider
# pool against the profile, so broader sourcing here doesn't dilute relevance.
KEYWORDS = [
    "AI automation",
    "AI automation engineer",
    "Claude Code",
    "n8n developer",
    "workflow automation",
    "LLM engineer",
    "prompt engineer",
    "AI agent developer",
    "AI agent engineer",
    "conversational AI developer",
    "voice AI developer",
    "AI chatbot developer",
    "AI integration engineer",
    "AI solutions engineer",
    "AI implementation specialist",
    "no-code AI developer",
    "forward deployed engineer",
    "Voiceflow developer",
    "RAG engineer",
]

import random

# Rotate through several recent desktop browsers — single thin UA gets 403'd
# from datacenter IPs (cloud routine). These mirror Chrome 130 / Firefox 131 /
# Safari 17 fingerprints exactly enough to pass simple WAF rules.
UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]
UA = UA_POOL[0]


def _browser_headers(ua=None, accept_json=False, referer=None):
    h = {
        "User-Agent": ua or random.choice(UA_POOL),
        "Accept": "application/json, text/plain, */*" if accept_json else
                  "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "empty" if accept_json else "document",
        "Sec-Fetch-Mode": "cors" if accept_json else "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        h["Referer"] = referer
    return h


HEADERS = _browser_headers()


def fetch(url, *, accept_json=False, referer=None, timeout=20, retries=2):
    """GET with rotating UA + retry on 403/429/5xx. Returns Response or None."""
    last = None
    for attempt in range(retries + 1):
        ua = random.choice(UA_POOL)
        try:
            r = requests.get(
                url,
                headers=_browser_headers(ua=ua, accept_json=accept_json, referer=referer),
                timeout=timeout,
            )
            last = r
            if r.status_code in (403, 429) or r.status_code >= 500:
                # Backoff with jitter, then retry with different UA
                time.sleep(1.5 + random.random() * 2.0)
                continue
            return r
        except requests.RequestException as e:
            print(f"  [fetch retry {attempt}] {url[:80]}: {e}")
            time.sleep(1.0 + random.random())
    return last


# ── LinkedIn (guest jobs API, no auth) ────────────────────────────────────────
def scrape_linkedin(keywords=KEYWORDS, max_per_keyword=10):
    """Use LinkedIn's public guest jobs endpoint. Global remote roles."""
    jobs = []
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in keywords:
        try:
            params = {
                "keywords": kw,
                "location": "United States",
                "f_WT": "2",  # remote
                "f_TPR": "r86400",  # last 24 hours
                "start": 0,
            }
            qs = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
            r = fetch(f"{base}?{qs}", referer="https://www.linkedin.com/jobs/")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [LinkedIn] {kw}: HTTP {code}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("li, div.base-card")
            count = 0
            for card in cards:
                a = card.select_one("a.base-card__full-link, a.base-card__title-link, a")
                title_el = card.select_one("h3, .base-search-card__title")
                comp_el = card.select_one("h4, .base-search-card__subtitle")
                time_el = card.select_one("time")
                if not (a and title_el):
                    continue
                url = a.get("href", "").split("?")[0]
                if not url.startswith("http"):
                    continue
                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": comp_el.get_text(strip=True) if comp_el else "",
                    "url": url,
                    "posted": time_el.get("datetime", "") if time_el else "",
                    "salary": "",
                    "source": "LinkedIn",
                    "summary": f"Search: {kw}",
                })
                count += 1
                if count >= max_per_keyword:
                    break
            print(f"  [LinkedIn] {kw}: {count} jobs")
            time.sleep(1.0)
        except Exception as e:
            print(f"  [LinkedIn ERROR] {kw}: {e}")
    return jobs


# ── Wellfound (formerly AngelList) — public job search HTML ───────────────────
def scrape_wellfound(keywords=KEYWORDS, max_per_keyword=8):
    """Wellfound public role search. Targets remote roles only."""
    jobs = []
    for kw in keywords:
        try:
            url = f"https://wellfound.com/role/r/{quote_plus(kw.lower().replace(' ', '-'))}?remote=true"
            r = fetch(url, referer="https://wellfound.com/")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [Wellfound] {kw}: HTTP {code}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            count = 0
            for a in soup.select("a[href*='/jobs/']"):
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if not title or len(title) < 6:
                    continue
                full = href if href.startswith("http") else f"https://wellfound.com{href}"
                jobs.append({
                    "title": title[:200],
                    "company": "",
                    "url": full,
                    "posted": "",
                    "salary": "",
                    "source": "Wellfound",
                    "summary": f"Search: {kw}",
                })
                count += 1
                if count >= max_per_keyword:
                    break
            print(f"  [Wellfound] {kw}: {count} jobs")
            time.sleep(1.0)
        except Exception as e:
            print(f"  [Wellfound ERROR] {kw}: {e}")
    return jobs


# ── Indeed (global remote) ────────────────────────────────────────────────────
def scrape_indeed(keywords=KEYWORDS, max_per_keyword=8):
    jobs = []
    for kw in keywords:
        try:
            url = f"https://www.indeed.com/jobs?q={quote_plus(kw)}&l=Remote&fromage=1&sc=0kf%3Aattr%28DSQF7%29%3B"
            r = fetch(url, referer="https://www.indeed.com/")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [Indeed] {kw}: HTTP {code}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            count = 0
            for card in soup.select("a.tapItem, a.jcs-JobTitle, a[data-jk]"):
                title_el = card.select_one("h2, span[title]")
                if not title_el:
                    continue
                jk = card.get("data-jk") or ""
                href = card.get("href", "")
                full = f"https://www.indeed.com/viewjob?jk={jk}" if jk else (href if href.startswith("http") else f"https://www.indeed.com{href}")
                comp_el = card.select_one("span.companyName, [data-testid='company-name']")
                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": comp_el.get_text(strip=True) if comp_el else "",
                    "url": full,
                    "posted": "",
                    "salary": "",
                    "source": "Indeed",
                    "summary": f"Search: {kw}",
                })
                count += 1
                if count >= max_per_keyword:
                    break
            print(f"  [Indeed] {kw}: {count} jobs")
            time.sleep(1.5)
        except Exception as e:
            print(f"  [Indeed ERROR] {kw}: {e}")
    return jobs


# ── Remotive (public JSON API, no auth) ───────────────────────────────────────
def scrape_remotive(keywords=KEYWORDS, max_per_keyword=12):
    """Remotive's public API: https://remotive.com/api/remote-jobs?search=<kw>"""
    jobs = []
    for kw in keywords:
        try:
            url = f"https://remotive.com/api/remote-jobs?search={quote_plus(kw)}&limit=40"
            r = fetch(url, accept_json=True, referer="https://remotive.com/")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [Remotive] {kw}: HTTP {code}")
                continue
            data = r.json()
            count = 0
            for d in data.get("jobs", []):
                jobs.append({
                    "title": (d.get("title") or "")[:200],
                    "company": d.get("company_name") or "",
                    "url": d.get("url") or "",
                    "posted": d.get("publication_date") or "",
                    "salary": d.get("salary") or "",
                    "source": "Remotive",
                    "summary": (d.get("description") or "")[:300],
                })
                count += 1
                if count >= max_per_keyword:
                    break
            print(f"  [Remotive] {kw}: {count} jobs")
            time.sleep(0.6)
        except Exception as e:
            print(f"  [Remotive ERROR] {kw}: {e}")
    return jobs


# ── We Work Remotely (RSS feed for remote programming) ───────────────────────
def scrape_weworkremotely(keywords=KEYWORDS, max_total=40):
    """RSS feed; filter titles by AI/automation keywords."""
    jobs = []
    try:
        import xml.etree.ElementTree as ET
        url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
        r = fetch(url, referer="https://weworkremotely.com/")
        if r is None or r.status_code != 200:
            code = r.status_code if r is not None else "ERR"
            print(f"  [WWR] HTTP {code}")
            return jobs
        root = ET.fromstring(r.content)
        kw_lower = [k.lower() for k in keywords] + ["ai", "llm", "automation", "agent"]
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()
            blob = f"{title} {desc}".lower()
            if not any(k in blob for k in kw_lower):
                continue
            company = ""
            if ":" in title:
                company = title.split(":", 1)[0].strip()
                title = title.split(":", 1)[1].strip()
            jobs.append({
                "title": title[:200],
                "company": company,
                "url": link,
                "posted": pub,
                "salary": "",
                "source": "We Work Remotely",
                "summary": desc[:300],
            })
            if len(jobs) >= max_total:
                break
        print(f"  [WWR] {len(jobs)} matched jobs")
    except Exception as e:
        print(f"  [WWR ERROR] {e}")
    return jobs


# ── Himalayas (public JSON listings) ──────────────────────────────────────────
def scrape_himalayas(keywords=KEYWORDS, max_per_keyword=10):
    """Himalayas public job listings JSON."""
    jobs = []
    for kw in keywords:
        try:
            url = f"https://himalayas.app/jobs/api?title={quote_plus(kw)}&limit=50"
            r = fetch(url, accept_json=True, referer="https://himalayas.app/jobs")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [Himalayas] {kw}: HTTP {code}")
                continue
            try:
                data = r.json()
            except Exception:
                print(f"  [Himalayas] {kw}: non-JSON response")
                continue
            rows = data.get("jobs") or data.get("results") or []
            count = 0
            for d in rows:
                title = (d.get("title") or "").strip()
                slug = d.get("slug") or ""
                company = (d.get("companyName") or (d.get("company") or {}).get("name") or "")
                href = d.get("applicationLink") or (f"https://himalayas.app/companies/{(d.get('company') or {}).get('slug','')}/jobs/{slug}" if slug else "")
                jobs.append({
                    "title": title[:200],
                    "company": company,
                    "url": href,
                    "posted": d.get("pubDate") or d.get("publishedAt") or "",
                    "salary": (
                        f"${d.get('minSalary')}-${d.get('maxSalary')}"
                        if d.get("minSalary") else ""
                    ),
                    "source": "Himalayas",
                    "summary": (d.get("excerpt") or d.get("description") or "")[:300],
                })
                count += 1
                if count >= max_per_keyword:
                    break
            print(f"  [Himalayas] {kw}: {count} jobs")
            time.sleep(0.6)
        except Exception as e:
            print(f"  [Himalayas ERROR] {kw}: {e}")
    return jobs


# ── X / Twitter — via Nitter mirrors (no API key) ────────────────────────────
def scrape_twitter(keywords=KEYWORDS, max_per_keyword=5):
    """Hits a Nitter mirror for hiring tweets. Best-effort; mirrors rotate."""
    jobs = []
    mirrors = ["https://nitter.net", "https://nitter.poast.org", "https://nitter.cz"]
    for kw in keywords[:3]:  # limit; this is noisy
        q = f'"{kw}" hiring remote'
        for mirror in mirrors:
            try:
                url = f"{mirror}/search?f=tweets&q={quote_plus(q)}"
                r = fetch(url, referer=mirror, timeout=15, retries=1)
                if r is None or r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                count = 0
                for tweet in soup.select(".tweet-content"):
                    text = tweet.get_text(strip=True)
                    if "hiring" not in text.lower() and "we're looking" not in text.lower():
                        continue
                    parent = tweet.find_parent("div", class_="timeline-item")
                    link_el = parent.select_one("a.tweet-link") if parent else None
                    href = link_el.get("href", "") if link_el else ""
                    full = f"https://x.com{href}" if href.startswith("/") else href
                    jobs.append({
                        "title": text[:140],
                        "company": "",
                        "url": full,
                        "posted": "",
                        "salary": "",
                        "source": "X/Twitter",
                        "summary": text[:300],
                    })
                    count += 1
                    if count >= max_per_keyword:
                        break
                print(f"  [Twitter via {mirror}] {kw}: {count} hits")
                if count > 0:
                    break  # mirror worked, move to next keyword
            except Exception as e:
                print(f"  [Twitter ERROR] {kw} via {mirror}: {e}")
                continue
    return jobs


# ── RemoteOK (public JSON API, no auth) ───────────────────────────────────────
def scrape_remoteok(keywords=KEYWORDS, max_total=70):
    """RemoteOK exposes a public JSON feed. Filter by AI/automation keywords."""
    jobs = []
    try:
        url = "https://remoteok.com/api"
        r = fetch(url, accept_json=True, referer="https://remoteok.com/")
        if r is None or r.status_code != 200:
            code = r.status_code if r is not None else "ERR"
            print(f"  [RemoteOK] HTTP {code}")
            return jobs
        data = r.json()
        # First entry is metadata
        rows = [d for d in data if isinstance(d, dict) and d.get("position")]
        kw_lower = [k.lower() for k in keywords] + ["ai", "llm", "automation", "agent", "n8n"]
        for d in rows:
            title = (d.get("position") or "").strip()
            tags = " ".join(d.get("tags") or []).lower()
            blob = f"{title} {tags} {(d.get('description') or '')[:200]}".lower()
            if not any(k in blob for k in kw_lower):
                continue
            jobs.append({
                "title": title[:200],
                "company": (d.get("company") or "").strip(),
                "url": d.get("url") or d.get("apply_url") or "",
                "posted": d.get("date") or "",
                "salary": (
                    f"${d.get('salary_min')}-${d.get('salary_max')}"
                    if d.get("salary_min") else ""
                ),
                "source": "RemoteOK",
                "summary": (d.get("description") or "")[:300],
            })
            if len(jobs) >= max_total:
                break
        print(f"  [RemoteOK] {len(jobs)} matched jobs")
    except Exception as e:
        print(f"  [RemoteOK ERROR] {e}")
    return jobs


# ── Greenhouse public boards (no auth, JSON, datacenter-friendly) ─────────────
GREENHOUSE_BOARDS = [
    # Verified 2026-05: 200 OK from boards-api.greenhouse.io
    "anthropic", "scaleai", "databricks", "gleanwork", "datadog",
    "stripe", "figma", "asana", "vercel", "discord", "wayve",
    "togetherai", "imbue", "magic",
    # AI-automation companies the user is targeting (n8n, Voiceflow, Bardeen,
    # Pipedream, Make, Zapier, Lindy, Replit, Cursor). Slugs that 404 are
    # gracefully skipped by fetch() retry/log path; harmless to include.
    "n8n", "voiceflow", "bardeen", "pipedream", "make", "zapier",
    "replit", "lindy", "cursor",
]

GREENHOUSE_KEYWORDS = [
    "ai", "ml", " llm", "automation", "agent", "applied",
    "claude", "n8n", "prompt", "workflow", "voiceflow", "relevance",
    "forward deployed", "solutions engineer", "implementation",
    "rag", "voice ai", "chatbot", "no-code", "low-code",
]


def scrape_greenhouse(boards=GREENHOUSE_BOARDS, max_per_board=15):
    """Pull AI/automation roles from public Greenhouse boards. Direct apply URLs."""
    jobs = []
    for slug in boards:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
            r = fetch(url, accept_json=True, referer=f"https://boards.greenhouse.io/{slug}")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [Greenhouse:{slug}] HTTP {code}")
                continue
            data = r.json()
            count = 0
            for j in data.get("jobs", []):
                title = (j.get("title") or "").strip()
                tlow = title.lower()
                if not any(k in tlow for k in GREENHOUSE_KEYWORDS):
                    continue
                loc = (j.get("location") or {}).get("name", "") or ""
                loc_l = loc.lower()
                if not any(tok in loc_l for tok in _WORLDWIDE_TOKENS):
                    continue
                if any(tok in loc_l for tok in _REGION_LOCK_TOKENS):
                    continue
                jobs.append({
                    "title": title[:200],
                    "company": slug.title(),
                    "url": j.get("absolute_url", ""),
                    "posted": j.get("updated_at") or "",
                    "salary": "",
                    "source": f"Greenhouse:{slug}",
                    "location": loc,
                    "summary": f"{loc or 'Remote'} | direct apply",
                })
                count += 1
                if count >= max_per_board:
                    break
            print(f"  [Greenhouse:{slug}] {count} matched jobs")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [Greenhouse:{slug} ERROR] {e}")
    return jobs


# ── Lever public boards ───────────────────────────────────────────────────────
LEVER_BOARDS = [
    # Verified 2026-05: 200 OK from api.lever.co. Many AI orgs (Harvey, ElevenLabs,
    # Sierra, Cresta, Decagon, Perplexity) migrated to Ashby — see scrape_ashby below.
    "mistral", "anyscale", "neon", "binance", "toptal",
    # AI-automation targets (Relevance AI, Crew AI, Clay, Tana). Bad slugs are
    # logged and skipped gracefully by the per-board try/except in scrape_lever.
    "relevanceai", "crewai", "clay", "tana",
]


def scrape_lever(boards=LEVER_BOARDS, max_per_board=15):
    """Pull AI/automation roles from public Lever boards."""
    jobs = []
    for slug in boards:
        try:
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            r = fetch(url, accept_json=True, referer=f"https://jobs.lever.co/{slug}")
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else "ERR"
                print(f"  [Lever:{slug}] HTTP {code}")
                continue
            data = r.json() or []
            count = 0
            for j in data:
                title = (j.get("text") or "").strip()
                tlow = title.lower()
                if not any(k in tlow for k in GREENHOUSE_KEYWORDS):
                    continue
                cats = j.get("categories") or {}
                loc = cats.get("location", "") or ""
                commitment = cats.get("commitment", "") or ""
                team = cats.get("team", "") or ""
                loc_l = loc.lower()
                if not any(tok in loc_l for tok in _WORLDWIDE_TOKENS):
                    continue
                if any(tok in loc_l for tok in _REGION_LOCK_TOKENS):
                    continue
                jobs.append({
                    "title": title[:200],
                    "company": slug.title(),
                    "url": j.get("hostedUrl") or j.get("applyUrl") or "",
                    "posted": "",
                    "salary": "",
                    "source": f"Lever:{slug}",
                    "location": loc,
                    "summary": f"{team or ''} | {loc or 'Remote'} | {commitment or ''} | direct apply".strip(" |"),
                })
                count += 1
                if count >= max_per_board:
                    break
            print(f"  [Lever:{slug}] {count} matched jobs")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [Lever:{slug} ERROR] {e}")
    return jobs


# ── Ashby public boards (most modern AI ATS — Harvey, ElevenLabs, Cohere, etc.)
ASHBY_BOARDS = [
    # Verified 2026-05: 200 OK from api.ashbyhq.com
    "harvey", "mistral", "vanta", "elevenlabs", "sierra",
    "cohere", "ramp", "decagon", "perplexity", "writer",
    "modal", "linear",
]


def scrape_ashby(boards=ASHBY_BOARDS, max_per_board=15):
    """Pull AI/automation roles from public Ashby job boards.

    Note: we bypass fetch() here because Ashby's CDN returns brotli-encoded
    responses when Accept-Encoding includes ``br``, and the ``brotli`` package
    isn't a hard dependency. Use minimal headers so requests negotiates gzip.
    """
    jobs = []
    ashby_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    for slug in boards:
        try:
            url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"
            r = requests.get(url, headers=ashby_headers, timeout=20)
            if r.status_code != 200:
                print(f"  [Ashby:{slug}] HTTP {r.status_code}")
                continue
            data = r.json() or {}
            count = 0
            for j in data.get("jobs", []):
                title = (j.get("title") or "").strip()
                tlow = title.lower()
                if not any(k in tlow for k in GREENHOUSE_KEYWORDS):
                    continue
                if not j.get("isListed", True):
                    continue
                # Worldwide-remote only — drop US-only & region-locked listings.
                loc = (j.get("location") or "").strip()
                workplace = (j.get("workplaceType") or "").lower()
                blob_l = f"{loc} {workplace}".lower()
                is_remote = bool(j.get("isRemote")) or any(tok in blob_l for tok in _WORLDWIDE_TOKENS)
                if not is_remote:
                    continue
                if any(tok in blob_l for tok in _REGION_LOCK_TOKENS):
                    continue
                jobs.append({
                    "title": title[:200],
                    "company": slug.title(),
                    "url": j.get("jobUrl") or j.get("applyUrl") or "",
                    "posted": j.get("publishedAt") or "",
                    "salary": "",
                    "source": f"Ashby:{slug}",
                    "location": loc,
                    "summary": f"{j.get('department','') or ''} | {loc or 'Remote'} | {j.get('employmentType','') or ''} | direct apply".strip(" |"),
                })
                count += 1
                if count >= max_per_board:
                    break
            print(f"  [Ashby:{slug}] {count} matched jobs")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [Ashby:{slug} ERROR] {e}")
    return jobs


# ── Hacker News "Who is hiring" via Algolia API ───────────────────────────────
def scrape_hn_hiring(keywords=KEYWORDS, max_total=35):
    """Algolia HN search — public, no auth. Pulls recent hiring comments."""
    jobs = []
    try:
        # Search HN comments (which is where "Who is hiring" replies live)
        terms = "AI%20OR%20LLM%20OR%20automation%20OR%20agent"
        url = (
            "https://hn.algolia.com/api/v1/search_by_date"
            f"?query={terms}&tags=comment&hitsPerPage=80"
        )
        r = fetch(url, accept_json=True, referer="https://hn.algolia.com/")
        if r is None or r.status_code != 200:
            code = r.status_code if r is not None else "ERR"
            print(f"  [HN] HTTP {code}")
            return jobs
        import re as _re
        # Signals that a comment is an actual hiring post (not chatter or a
        # "Seeking work" reply). HN "Who is hiring" entries are either prose with
        # one of these, or the "Company | Role | LOCATION | REMOTE | ..." template.
        hiring_signals = (
            "hiring", "we're looking", "we are looking", "looking for",
            "join our", "join us", "apply at", "apply here", "careers",
            "now hiring", "is hiring", "we need", "open role", "open position",
        )
        for h in r.json().get("hits", []):
            text = (h.get("comment_text") or "")
            low0 = text.lower()
            if "remote" not in low0:
                continue
            # Strip HTML
            clean = _re.sub(r"<[^>]+>", " ", text)
            clean = _re.sub(r"\s+", " ", clean).strip()
            if len(clean) < 80:
                continue
            low = clean.lower()
            # Drop "Seeking work" / freelancer-available replies (wrong thread).
            if "seeking work" in low[:60] or "want to be hired" in low:
                continue
            has_signal = any(s in low for s in hiring_signals)
            has_template = clean.count("|") >= 2
            if not (has_signal or has_template):
                continue
            # Pull company + role from the pipe template when present.
            parts = [p.strip() for p in clean.split("|") if p.strip()]
            if len(parts) >= 2:
                company, title = parts[0][:80], parts[1][:140]
            else:
                company, title = "", clean[:140]
            jobs.append({
                "title": title,
                "company": company,
                "url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "posted": h.get("created_at", ""),
                "salary": "",
                "source": "HN Who is hiring",
                "summary": clean[:300],
            })
            if len(jobs) >= max_total:
                break
        print(f"  [HN] {len(jobs)} hiring posts")
    except Exception as e:
        print(f"  [HN ERROR] {e}")
    return jobs


# ── Post-scrape filters ───────────────────────────────────────────────────────
# Tokens that *positively* indicate a worldwide-remote listing.
_WORLDWIDE_TOKENS = ("remote", "anywhere", "global", "worldwide")

# Tokens that mark a listing as country/region-locked. If any appear in the
# location string, the listing is rejected even if it also contains a
# worldwide token (e.g. "Remote (US only)").
_REGION_LOCK_TOKENS = (
    "us only", "usa only", "united states only", "us-only", "us residents",
    "us-based", "us based", "must be based in", "based in the us",
    "must reside in", "must live in", "residents of",
    "(us)", "(usa)", "- usa", "- us", "us/canada only",
    "americas only", "north america only",
    "emea only", "europe only", "eu only", "uk only", "uk-only",
    "apac only", "asia only", "india only", "canada only", "australia only",
    "latam only", "latin america only",
)


def is_worldwide_remote(job):
    """True iff the job's location/region indicates remote-anywhere.

    Used post-scrape to drop US-only or otherwise country-locked "remote"
    listings. If no location signal is present at all (some boards omit it),
    the job is rejected — we cannot prove it's worldwide-remote.
    """
    parts = [
        (job.get("location") or ""),
        (job.get("summary") or "")[:400],
        (job.get("title") or ""),
    ]
    blob = " ".join(parts).lower()
    if not blob.strip():
        return False
    if any(tok in blob for tok in _REGION_LOCK_TOKENS):
        return False
    return any(tok in blob for tok in _WORLDWIDE_TOKENS)


_SENIOR_TITLE_TOKENS = (
    "senior", " sr.", " sr ", "sr.", "lead ", " lead", "principal",
    "staff ", " staff", "director", "head of", "manager", "architect",
    "vp ", "vp,", "chief ",
)
_SENIOR_DESC_PHRASES = (
    "5+ years", "6+ years", "7+ years", "8+ years", "9+ years", "10+ years",
    "minimum 5 years", "minimum 6 years", "minimum 7 years", "minimum 8 years",
    "at least 5 years", "at least 6 years", "at least 7 years",
    "5-7 years", "5-10 years", "7-10 years",
)
_JUNIOR_TOKENS = (
    "entry", "junior", " jr.", " jr ", "jr.", "new grad", "associate",
    "intern", "no experience", "0-1 year", "0-2 year", "0 to 1 year",
    "0 to 2 year", "graduate program", "early career",
)


def is_entry_level(job):
    """True if title/description looks entry-level / junior / no-experience.

    Reject hits (returns False) for explicit senior, lead, principal, staff,
    manager, director, or 5+-year-experience descriptions. Accept hits when
    junior signals are present, or when nothing in either field flags
    seniority (default-accept: many listings simply don't state level).
    """
    title = (job.get("title") or "").lower()
    desc = (job.get("summary") or "").lower()
    # Hard reject on senior-title markers.
    for tok in _SENIOR_TITLE_TOKENS:
        if tok in f" {title} ":
            return False
    # Hard reject on "5+ years" style descriptions.
    for phrase in _SENIOR_DESC_PHRASES:
        if phrase in desc:
            return False
    # Junior tokens always pass.
    for tok in _JUNIOR_TOKENS:
        if tok in f" {title} {desc} ":
            return True
    # No seniority signal in either field → accept.
    return True


# ── Orchestration ─────────────────────────────────────────────────────────────
def dedupe(jobs):
    """Dedupe by URL, then by (title+company) lowercase."""
    seen_url = set()
    seen_pair = set()
    out = []
    for j in jobs:
        u = (j.get("url") or "").strip()
        pair = ((j.get("title", "") or "").lower().strip(), (j.get("company", "") or "").lower().strip())
        if u and u in seen_url:
            continue
        if pair[0] and pair in seen_pair:
            continue
        if u:
            seen_url.add(u)
        if pair[0]:
            seen_pair.add(pair)
        out.append(j)
    return out


def _posted_dt(job):
    """Best-effort parse of a job's `posted` field to an aware datetime.

    Handles ISO 8601 (Greenhouse/Ashby/Remotive/RemoteOK/HN/Himalayas, incl.
    trailing 'Z') and RFC 822 (We Work Remotely pubDate). Returns None when the
    field is empty or unparseable (Lever omits it) — callers treat None as
    'undated, keep it'.
    """
    s = (job.get("posted") or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    return None


def apply_freshness_and_dedup(jobs):
    """Drop stale postings and rotate out roles already shown recently.

    1. Freshness: drop jobs whose posting date is older than JOBS_FRESH_DAYS.
       Undated jobs (no parseable `posted`) are kept — can't prove they're stale.
    2. Cross-run dedup: prefer jobs not surfaced in the last JOBS_SEEN_DAYS days
       (per data/jobs_seen.json). If that leaves fewer than JOBS_MIN_POOL, backfill
       with recently-shown ones so a slow scrape day never starves the section.
    """
    fresh_days = int(os.environ.get("JOBS_FRESH_DAYS", "45"))
    seen_days = int(os.environ.get("JOBS_SEEN_DAYS", "7"))
    min_pool = int(os.environ.get("JOBS_MIN_POOL", "15"))
    now = datetime.now(timezone.utc)

    fresh, dropped_stale = [], 0
    for j in jobs:
        dt = _posted_dt(j)
        if dt is not None and (now - dt).days > fresh_days:
            dropped_stale += 1
            continue
        fresh.append(j)

    try:
        from tools.job_history import recently_seen_urls, load_history
        recent = recently_seen_urls(seen_days)
        last_shown = load_history()                      # {url: "YYYY-MM-DD"}
    except Exception as e:
        print(f"  [dedup] history unavailable ({e}) — skipping cross-run dedup")
        recent, last_shown = set(), {}

    new_jobs = [j for j in fresh if (j.get("url") or "") not in recent]
    repeat_jobs = [j for j in fresh if (j.get("url") or "") in recent]
    if len(new_jobs) < min_pool and repeat_jobs:
        # Thin scrape day: backfill with recently-shown roles, but surface the
        # LEAST-recently-seen first so the section rotates the back-catalog
        # instead of replaying the same roles every run.
        repeat_jobs.sort(key=lambda j: last_shown.get(j.get("url") or "", ""))
        backfill = repeat_jobs[: max(0, min_pool - len(new_jobs))]
        new_jobs += backfill
    print(
        f"[freshness] {len(jobs)} -> {len(fresh)} within {fresh_days}d "
        f"(dropped {dropped_stale} stale); dedup held back "
        f"{len(fresh) - len(new_jobs)} role(s) shown in last {seen_days}d"
    )
    return new_jobs


def score(j):
    """Higher = more relevant. Prioritize AI automation matches in title."""
    t = (j.get("title", "") or "").lower()
    blob = f"{t} {(j.get('location') or '').lower()} {(j.get('summary') or '').lower()[:200]}"
    s = 0
    if "automat" in t:
        s += 3
    if "ai" in t or "llm" in t:
        s += 2
    if "claude" in t or "n8n" in t or "agent" in t:
        s += 2
    if "remote" in t:
        s += 1
    if "intern" in t:
        s += 1
    if "worldwide" in blob or "anywhere" in blob or "global" in blob:
        s += 1
    return s


def scrape_all_jobs():
    os.makedirs(TMP_DIR, exist_ok=True)
    all_jobs = []

    print(f"[config] JOBS_FRAGILE_SOURCES={'on' if INCLUDE_FRAGILE else 'off (cloud-safe)'}")

    if INCLUDE_FRAGILE:
        print("[fragile] LinkedIn ...")
        try:
            all_jobs += scrape_linkedin()
        except Exception as e:
            print(f"  LinkedIn fatal: {e}")

        print("[fragile] Wellfound ...")
        try:
            all_jobs += scrape_wellfound()
        except Exception as e:
            print(f"  Wellfound fatal: {e}")

        print("[fragile] Indeed ...")
        try:
            all_jobs += scrape_indeed()
        except Exception as e:
            print(f"  Indeed fatal: {e}")

        print("[fragile] Twitter/X via Nitter ...")
        try:
            all_jobs += scrape_twitter()
        except Exception as e:
            print(f"  Twitter fatal: {e}")
    else:
        print("[fragile] Skipping LinkedIn/Wellfound/Indeed/Twitter — datacenter IPs hard-block these (set JOBS_FRAGILE_SOURCES=1 to override)")

    print("[reliable] Remotive ...")
    try:
        all_jobs += scrape_remotive()
    except Exception as e:
        print(f"  Remotive fatal: {e}")

    print("[reliable] We Work Remotely ...")
    try:
        all_jobs += scrape_weworkremotely()
    except Exception as e:
        print(f"  WWR fatal: {e}")

    print("[reliable] Himalayas ...")
    try:
        all_jobs += scrape_himalayas()
    except Exception as e:
        print(f"  Himalayas fatal: {e}")

    print("[reliable] RemoteOK ...")
    try:
        all_jobs += scrape_remoteok()
    except Exception as e:
        print(f"  RemoteOK fatal: {e}")

    print("[reliable] Hacker News hiring ...")
    try:
        all_jobs += scrape_hn_hiring()
    except Exception as e:
        print(f"  HN fatal: {e}")

    print("[ATS] Greenhouse public boards ...")
    try:
        all_jobs += scrape_greenhouse()
    except Exception as e:
        print(f"  Greenhouse fatal: {e}")

    print("[ATS] Lever public boards ...")
    try:
        all_jobs += scrape_lever()
    except Exception as e:
        print(f"  Lever fatal: {e}")

    print("[ATS] Ashby public boards ...")
    try:
        all_jobs += scrape_ashby()
    except Exception as e:
        print(f"  Ashby fatal: {e}")

    deduped = dedupe(all_jobs)

    # Worldwide-remote + entry-level filter pass.
    pre_filter = len(deduped)
    after_remote = [j for j in deduped if is_worldwide_remote(j)]
    filtered = [j for j in after_remote if is_entry_level(j)]
    print(
        f"[filter] {pre_filter} unique → {len(after_remote)} worldwide-remote → "
        f"{len(filtered)} entry-level"
    )

    # Freshness + cross-run dedup so the daily list rotates instead of repeating.
    filtered = apply_freshness_and_dedup(filtered)
    if len(filtered) < 5:
        print(
            f"  WARN: only {len(filtered)} jobs survive worldwide-remote + entry-level "
            "filters. Heuristics may be too strict — review _WORLDWIDE_TOKENS / "
            "_SENIOR_TITLE_TOKENS in tools/scrape_jobs.py."
        )

    filtered.sort(key=score, reverse=True)

    out = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_raw": len(all_jobs),
        "total_unique": pre_filter,
        "total_after_filter": len(filtered),
        "jobs": filtered,
    }

    with open(JOBS_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    with open(JOBS_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "company", "url", "source", "posted", "salary"])
        for j in filtered:
            w.writerow([
                j.get("title", ""),
                j.get("company", ""),
                j.get("url", ""),
                j.get("source", ""),
                j.get("posted", ""),
                j.get("salary", ""),
            ])

    print(f"\nDone. {len(filtered)} jobs after filter → {JOBS_JSON}")
    print(f"CSV → {JOBS_CSV}")
    return filtered


if __name__ == "__main__":
    scrape_all_jobs()
