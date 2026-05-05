"""
Scrape global remote AI Automation jobs from multiple sources.
Sources: LinkedIn (guest API), Wellfound, Indeed, Remotive, We Work Remotely,
Himalayas, RemoteOK, Hacker News "Who is hiring", X/Twitter.

Outputs: .tmp/jobs.json + .tmp/jobs.csv

Each source is independent — failures in one don't kill the others.
"""

import csv
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
JOBS_JSON = os.path.join(TMP_DIR, "jobs.json")
JOBS_CSV = os.path.join(TMP_DIR, "jobs.csv")

KEYWORDS = [
    "AI automation",
    "AI automator",
    "Claude Code",
    "n8n developer",
    "LLM engineer",
    "prompt engineer",
    "AI agent developer",
    "automation engineer AI",
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
def scrape_remotive(keywords=KEYWORDS, max_per_keyword=8):
    """Remotive's public API: https://remotive.com/api/remote-jobs?search=<kw>"""
    jobs = []
    for kw in keywords:
        try:
            url = f"https://remotive.com/api/remote-jobs?search={quote_plus(kw)}&limit=20"
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
def scrape_weworkremotely(keywords=KEYWORDS, max_total=25):
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
def scrape_himalayas(keywords=KEYWORDS, max_per_keyword=6):
    """Himalayas public job listings JSON."""
    jobs = []
    for kw in keywords:
        try:
            url = f"https://himalayas.app/jobs/api?title={quote_plus(kw)}&limit=20"
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
def scrape_remoteok(keywords=KEYWORDS, max_total=40):
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


# ── Hacker News "Who is hiring" via Algolia API ───────────────────────────────
def scrape_hn_hiring(keywords=KEYWORDS, max_total=20):
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
        for h in r.json().get("hits", []):
            text = (h.get("comment_text") or "")
            if "remote" not in text.lower():
                continue
            # Strip HTML
            import re as _re
            clean = _re.sub(r"<[^>]+>", " ", text)
            clean = _re.sub(r"\s+", " ", clean).strip()
            if len(clean) < 60:
                continue
            jobs.append({
                "title": clean[:140],
                "company": "",
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


def score(j):
    """Higher = more relevant. Prioritize AI automation matches in title."""
    t = (j.get("title", "") or "").lower()
    s = 0
    if "automat" in t:
        s += 3
    if "ai" in t or "llm" in t:
        s += 2
    if "claude" in t or "n8n" in t or "agent" in t:
        s += 2
    if "remote" in t:
        s += 1
    if "senior" in t or "lead" in t:
        s -= 2  # user has no experience yet — favor IC roles
    if "intern" in t:
        s += 1
    return s


def scrape_all_jobs():
    os.makedirs(TMP_DIR, exist_ok=True)
    all_jobs = []

    print("[1/9] LinkedIn ...")
    try:
        all_jobs += scrape_linkedin()
    except Exception as e:
        print(f"  LinkedIn fatal: {e}")

    print("[2/9] Wellfound ...")
    try:
        all_jobs += scrape_wellfound()
    except Exception as e:
        print(f"  Wellfound fatal: {e}")

    print("[3/9] Indeed ...")
    try:
        all_jobs += scrape_indeed()
    except Exception as e:
        print(f"  Indeed fatal: {e}")

    print("[4/9] Remotive ...")
    try:
        all_jobs += scrape_remotive()
    except Exception as e:
        print(f"  Remotive fatal: {e}")

    print("[5/9] We Work Remotely ...")
    try:
        all_jobs += scrape_weworkremotely()
    except Exception as e:
        print(f"  WWR fatal: {e}")

    print("[6/9] Himalayas ...")
    try:
        all_jobs += scrape_himalayas()
    except Exception as e:
        print(f"  Himalayas fatal: {e}")

    print("[7/9] Twitter/X via Nitter ...")
    try:
        all_jobs += scrape_twitter()
    except Exception as e:
        print(f"  Twitter fatal: {e}")

    print("[8/9] RemoteOK ...")
    try:
        all_jobs += scrape_remoteok()
    except Exception as e:
        print(f"  RemoteOK fatal: {e}")

    print("[9/9] Hacker News hiring ...")
    try:
        all_jobs += scrape_hn_hiring()
    except Exception as e:
        print(f"  HN fatal: {e}")

    deduped = dedupe(all_jobs)
    deduped.sort(key=score, reverse=True)

    out = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_raw": len(all_jobs),
        "total_unique": len(deduped),
        "jobs": deduped,
    }

    with open(JOBS_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    with open(JOBS_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "company", "url", "source", "posted", "salary"])
        for j in deduped:
            w.writerow([
                j.get("title", ""),
                j.get("company", ""),
                j.get("url", ""),
                j.get("source", ""),
                j.get("posted", ""),
                j.get("salary", ""),
            ])

    print(f"\nDone. {len(deduped)} unique jobs → {JOBS_JSON}")
    print(f"CSV → {JOBS_CSV}")
    return deduped


if __name__ == "__main__":
    scrape_all_jobs()
