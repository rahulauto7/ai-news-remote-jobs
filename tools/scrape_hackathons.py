"""
Scrape currently-open AI hackathons & competitions from major platforms.

Sources: Devpost, Kaggle, HuggingFace, MLH, lablab.ai, AIcrowd, DrivenData.
Plus extra Google News-style proxies as catch-all (in scrape_rss_feeds.py).

Each fetch_<platform>() is wrapped in try/except so one source failing
does not kill the run. Emits per-source ok/skipped/error counts to stderr.

Output: .tmp/hackathons.json
  {
    "scraped_at": "<iso>",
    "hackathons": [
      {
        "title": str,
        "apply_url": str,              # direct registration / submission page
        "platform": str,                # Devpost | Kaggle | HuggingFace | MLH | lablab.ai | AIcrowd | DrivenData
        "deadline_iso": "YYYY-MM-DD" | null,
        "prize_summary": str | null,
        "tags": [str, ...],
        "description": str,
        "region": "Worldwide" | str,
        "discovered_at": "<iso>"
      },
      ...
    ]
  }

Sorted by deadline_iso ascending; null deadlines last.
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

_TAG_RE = re.compile(r"<[^>]+>")
def _strip_html(s):
    if not s:
        return s
    return _TAG_RE.sub("", str(s)).strip()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "hackathons.json")

TIMEOUT = 20

UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0",
]


def _headers():
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # No "br": requests has no brotli decoder unless the brotli package is
        # installed. Cloudflare-fronted sites (e.g. lablab.ai) honour "br" and
        # return brotli, which then decodes to garbage. gzip/deflate are native.
        "Accept-Encoding": "gzip, deflate",
    }


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# AI keyword vocabulary + word-boundary matcher live in tools/_text_match.py
# so jobs, hackathons, and Instagram-reel discovery share one source of truth.
from tools._text_match import (
    AI_KEYWORDS_WORD, AI_KEYWORDS_PHRASE, matches_ai as passes_ai_filter,
)


def _parse_deadline(raw):
    """Try hard to extract a YYYY-MM-DD from many string formats. Returns None on failure."""
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return None
    s = str(raw).strip()
    if not s:
        return None

    # ISO 8601 leading: 2026-06-15 or 2026-06-15T18:00:00Z
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except ValueError:
            pass

    # Devpost format: "Apr 01 - May 31, 2026" or "Apr 01, 2026 - May 31, 2026"
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }
    # Capture LAST month-day-year pattern in the string (this is usually the end/deadline).
    candidates = re.findall(
        r"([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        s,
    )
    if candidates:
        # Try last one; if it has no year, look for a year anywhere in the string
        year_match = re.search(r"\b(20\d{2})\b", s)
        default_year = int(year_match.group(1)) if year_match else datetime.now().year
        last_month, last_day, last_year = candidates[-1]
        mnum = months.get(last_month.lower())
        if mnum:
            yr = int(last_year) if last_year else default_year
            try:
                return date(yr, mnum, int(last_day)).isoformat()
            except ValueError:
                pass

    return None


def normalize_item(*, title, apply_url, platform, deadline_iso=None,
                   prize_summary=None, tags=None, description="", region="Worldwide",
                   eligibility=None, benefits=None):
    if not title or not apply_url:
        return None
    title = title.strip()
    apply_url = apply_url.strip()
    if not title or not apply_url:
        return None
    return {
        "title": title[:200],
        "apply_url": apply_url,
        "platform": platform,
        "deadline_iso": deadline_iso,
        "prize_summary": (prize_summary or None),
        "tags": list(tags) if tags else [],
        "description": (description or "").strip()[:500],
        "region": region or "Worldwide",
        # Plain-language accelerator fields for the PDF showcase block; other
        # sources leave these None.
        "eligibility": (eligibility or None),
        "benefits": (benefits or None),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Sources ───────────────────────────────────────────────────────────────────

def fetch_devpost(stats):
    """Devpost public JSON API. Most reliable + comprehensive source."""
    items = []
    page = 1
    while page <= 20:
        try:
            url = f"https://devpost.com/api/hackathons?status[]=open&page={page}"
            r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
            if r.status_code != 200:
                stats["errors"] += 1
                break
            data = r.json()
            hacks = data.get("hackathons", []) or []
            if not hacks:
                break
            for h in hacks:
                # Skip invite-only — user can't apply without an invite.
                if h.get("invite_only"):
                    stats["skipped"] += 1
                    continue
                # Skip if winners already announced.
                if h.get("winners_announced"):
                    stats["skipped"] += 1
                    continue
                title = h.get("title") or ""
                # Prefer the direct submission/start URL; fall back to homepage.
                apply_url = h.get("start_a_submission_url") or h.get("url") or ""
                themes = [t.get("name", "") for t in (h.get("themes") or []) if isinstance(t, dict)]
                description = (h.get("submission_period_dates") or "") + " " + " ".join(themes)
                # Strong AI signal: theme contains AI/ML, OR title contains AI keyword
                haystack = " ".join([title, " ".join(themes), h.get("organization_name") or ""])
                if not passes_ai_filter(haystack):
                    stats["skipped"] += 1
                    continue
                deadline_iso = _parse_deadline(h.get("submission_period_dates") or h.get("deadline"))
                prize_summary = _strip_html(h.get("prize_amount")) or None
                location = h.get("displayed_location") or {}
                region = "Worldwide"
                if isinstance(location, dict):
                    loc = location.get("location") or ""
                    if loc and loc.lower() != "online":
                        region = loc
                normalized = normalize_item(
                    title=title,
                    apply_url=apply_url,
                    platform="Devpost",
                    deadline_iso=deadline_iso,
                    prize_summary=prize_summary,
                    tags=themes,
                    description=h.get("submission_period_dates") or "",
                    region=region,
                )
                if normalized:
                    items.append(normalized)
                    stats["ok"] += 1
            page += 1
            time.sleep(0.5)
        except Exception as e:
            stats["errors"] += 1
            _log(f"[devpost] error page {page}: {e}")
            break
    return items


def fetch_kaggle(stats):
    """Kaggle competitions. Scrape the listing page; JSON-LD where available."""
    items = []
    try:
        url = "https://www.kaggle.com/competitions?listOption=active"
        r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            stats["errors"] += 1
            return items
        html = r.text
        # Kaggle is a JS SPA — but the initial HTML often contains an embedded
        # JSON blob with the competition list. Look for it.
        m = re.search(r'Kaggle\.State\.push\((\{.*?\})\);', html, re.DOTALL)
        embedded = None
        if m:
            try:
                embedded = json.loads(m.group(1))
            except Exception:
                embedded = None

        if embedded:
            comps = []
            def _walk(obj):
                if isinstance(obj, dict):
                    if "competitionTitle" in obj or ("title" in obj and "deadline" in obj):
                        comps.append(obj)
                    for v in obj.values():
                        _walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _walk(v)
            _walk(embedded)
            for c in comps:
                title = c.get("competitionTitle") or c.get("title") or ""
                slug = c.get("competitionUrl") or c.get("url") or ""
                if slug and not slug.startswith("http"):
                    slug = urljoin("https://www.kaggle.com", slug)
                if not (title and slug):
                    continue
                deadline_iso = _parse_deadline(c.get("deadline") or c.get("deadlineDate"))
                description = c.get("subtitle") or c.get("description") or ""
                if not passes_ai_filter(title + " " + description):
                    stats["skipped"] += 1
                    continue
                items.append(normalize_item(
                    title=title,
                    apply_url=slug,
                    platform="Kaggle",
                    deadline_iso=deadline_iso,
                    prize_summary=str(c.get("reward") or c.get("totalPrize") or "") or None,
                    tags=c.get("tags") or [],
                    description=description,
                ))
                stats["ok"] += 1
            return items

        # Fallback: parse <a href="/competitions/<slug>"> links.
        soup = BeautifulSoup(html, "lxml")
        seen = set()
        for a in soup.select('a[href^="/competitions/"]'):
            href = a.get("href") or ""
            if href in seen or "/competitions/?" in href or href == "/competitions":
                continue
            seen.add(href)
            title = a.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            apply_url = urljoin("https://www.kaggle.com", href)
            if not passes_ai_filter(title):
                stats["skipped"] += 1
                continue
            items.append(normalize_item(
                title=title,
                apply_url=apply_url,
                platform="Kaggle",
            ))
            stats["ok"] += 1
        return items
    except Exception as e:
        stats["errors"] += 1
        _log(f"[kaggle] error: {e}")
        return items


def fetch_huggingface(stats):
    """HuggingFace competitions page. All HF competitions are AI by definition.
    Skip filter/category tab URLs (/competitions/spaces, /competitions/models)."""
    items = []
    # HF's filter tabs — these are NOT competitions.
    HF_FILTER_PATHS = {
        "/competitions",
        "/competitions/spaces",
        "/competitions/models",
        "/competitions/datasets",
        "/competitions/active",
        "/competitions/upcoming",
        "/competitions/finished",
    }
    try:
        url = "https://huggingface.co/competitions"
        r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            stats["errors"] += 1
            return items
        soup = BeautifulSoup(r.text, "lxml")
        seen = set()
        for a in soup.select('a[href^="/competitions/"]'):
            href = (a.get("href") or "").split("?")[0].rstrip("/")
            if href in HF_FILTER_PATHS or href in seen:
                continue
            # Real competitions have a slug with at least one hyphen or a
            # competition owner/name pattern. Skip suspicious short paths.
            slug = href.replace("/competitions/", "")
            if not slug or "/" not in slug and "-" not in slug and len(slug) < 8:
                stats["skipped"] += 1
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 4:
                continue
            apply_url = urljoin("https://huggingface.co", href)
            parent = a.find_parent(["article", "div", "li"])
            card_text = parent.get_text(" ", strip=True) if parent else ""
            deadline_iso = _parse_deadline(card_text)
            items.append(normalize_item(
                title=title[:200],
                apply_url=apply_url,
                platform="HuggingFace",
                deadline_iso=deadline_iso,
                description=card_text[:400] if card_text else "",
            ))
            stats["ok"] += 1
        return items
    except Exception as e:
        stats["errors"] += 1
        _log(f"[huggingface] error: {e}")
        return items


def fetch_mlh(stats):
    """MLH season events. Cards use Tailwind classes — find via utm_source=mlh."""
    items = []
    try:
        year = datetime.now().year
        url = f"https://mlh.io/seasons/{year}/events"
        r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            url = f"https://mlh.io/seasons/{year + 1}/events"
            r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
            if r.status_code != 200:
                stats["errors"] += 1
                return items
        soup = BeautifulSoup(r.text, "lxml")
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "utm_source=mlh" not in href:
                continue
            base = href.split("?")[0]
            if base in seen:
                continue
            seen.add(base)
            title = a.get_text(" ", strip=True)
            if not title:
                heading = a.find(["h1", "h2", "h3", "h4"])
                title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 3:
                continue
            # Pull the card's surrounding text for date / description.
            card = a.find_parent("div")
            card_text = card.get_text(" ", strip=True) if card else ""
            haystack = title + " " + card_text
            if not passes_ai_filter(haystack):
                stats["skipped"] += 1
                continue
            items.append(normalize_item(
                title=title[:200],
                apply_url=href,
                platform="MLH",
                deadline_iso=_parse_deadline(card_text),
                description=card_text[:300] if card_text else "",
            ))
            stats["ok"] += 1
        return items
    except Exception as e:
        stats["errors"] += 1
        _log(f"[mlh] error: {e}")
        return items


def _lablab_extract_events(html):
    """Pull the `sortedEvents` array out of lablab.ai's Next.js RSC payload.

    lablab.ai is a server-rendered Next.js app — the event list is not in any
    <a> tags. It is streamed inside a `self.__next_f.push([1,"<js-string>"])`
    inline script, and the JS string contains `"sortedEvents":[ {...}, ... ]`.
    Returns a list of event dicts, or [] if the structure is not found.
    """
    soup = BeautifulSoup(html, "lxml")
    blob = None
    for s in soup.find_all("script"):
        t = s.string or s.get_text() or ""
        if "sortedEvents" in t and "__next_f" in t:
            blob = t
            break
    if not blob:
        return []

    # The script body is `self.__next_f.push([1,"...escaped js string..."])`.
    m = re.search(r'self\.__next_f\.push\(\[1,\s*"', blob)
    if not m:
        return []
    inner = blob[m.end() - 1:]          # keep the opening quote
    end = inner.rfind('"])')
    if end < 0:
        return []
    decoded = json.loads(inner[:end + 1])   # unescape the JS string literal

    # Balanced-bracket scan to extract the sortedEvents JSON array.
    idx = decoded.find('"sortedEvents":')
    if idx < 0:
        return []
    arr_start = decoded.find('[', idx)
    if arr_start < 0:
        return []
    depth, in_str, esc, arr_end = 0, False, False, -1
    for i in range(arr_start, len(decoded)):
        c = decoded[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    arr_end = i
                    break
    if arr_end < 0:
        return []
    return json.loads(decoded[arr_start:arr_end + 1])


def fetch_lablab(stats):
    """lablab.ai AI hackathons. All are AI by definition (type == HACKATHON).

    Parses the Next.js RSC payload (see _lablab_extract_events). Keeps only
    events that are still open or upcoming — endAt OR startAt today-or-later.
    deadline_iso uses endAt (the submission-window close)."""
    items = []
    try:
        url = "https://lablab.ai/event"
        r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            stats["errors"] += 1
            return items
        events = _lablab_extract_events(r.text)
        if not events:
            stats["errors"] += 1
            _log("[lablab] sortedEvents payload not found — site structure may have changed")
            return items

        today = date.today().isoformat()
        for e in events:
            if not isinstance(e, dict):
                continue
            title = (e.get("name") or "").strip()
            slug = (e.get("slug") or "").strip()
            if not title or not slug:
                stats["skipped"] += 1
                continue
            end_iso = _parse_deadline(e.get("endAt"))
            start_iso = _parse_deadline(e.get("startAt"))
            # Open or upcoming only: drop events whose window has fully passed.
            if not ((end_iso and end_iso >= today) or (start_iso and start_iso >= today)):
                stats["skipped"] += 1
                continue
            description = (e.get("description") or "").strip()
            # Best-effort prize: first "$amount" whose surrounding text mentions
            # "prize" — avoids false positives like "$100 in cloud credits".
            prize_summary = None
            for pm in re.finditer(r"\$\s?[\d][\d,]*(?:\.\d+)?\s?[KMB]?\+?", description):
                window = description[max(0, pm.start() - 35):pm.end() + 35].lower()
                if "prize" in window:
                    prize_summary = pm.group(0).strip()
                    break
            normalized = normalize_item(
                title=title,
                apply_url=urljoin("https://lablab.ai/event/", slug),
                platform="lablab.ai",
                deadline_iso=end_iso,
                prize_summary=prize_summary,
                description=description,
                region="Worldwide",
            )
            if normalized:
                items.append(normalized)
                stats["ok"] += 1
        return items
    except Exception as e:
        stats["errors"] += 1
        _log(f"[lablab] error: {e}")
        return items


def fetch_aicrowd(stats):
    """AIcrowd active challenges. Use h5.card-title for the real title; parse
    the badge tooltip for the true deadline. Drop post-challenge / completed
    items and placeholder-dated competitions (year > current+2)."""
    items = []
    try:
        url = "https://www.aicrowd.com/challenges?challenge_filter=active"
        r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            stats["errors"] += 1
            return items
        soup = BeautifulSoup(r.text, "lxml")
        cur_year = datetime.now().year
        for card in soup.select(".card-challenge"):
            title_a = card.select_one("h5.card-title a")
            if not title_a:
                continue
            title = title_a.get_text(strip=True)
            slug = title_a.get("href") or ""
            if not (title and slug):
                continue
            badge = card.select_one(".badge")
            badge_text = badge.get_text(" ", strip=True) if badge else ""
            badge_tooltip = (badge.get("title") if badge else "") or ""

            # Drop closed / past-window competitions.
            bt_low = badge_text.lower()
            if "post challenge" in bt_low or "completed" in bt_low or "closed" in bt_low:
                stats["skipped"] += 1
                continue

            # Parse deadline from tooltip ("2026-06-15 12:00:00 UTC") — fall back to None.
            deadline_iso = _parse_deadline(badge_tooltip)

            # Drop placeholder-dated legacy competitions (>2 years out).
            if deadline_iso:
                try:
                    deadline_year = int(deadline_iso[:4])
                    if deadline_year > cur_year + 2:
                        stats["skipped"] += 1
                        continue
                except ValueError:
                    pass

            desc_el = card.select_one(".card-text")
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            # AI filter as safety net (title + description).
            if not passes_ai_filter(title + " " + description):
                stats["skipped"] += 1
                continue

            apply_url = urljoin("https://www.aicrowd.com", slug.split("?")[0])
            items.append(normalize_item(
                title=title[:200],
                apply_url=apply_url,
                platform="AIcrowd",
                deadline_iso=deadline_iso,
                description=description[:400],
            ))
            stats["ok"] += 1
        return items
    except Exception as e:
        stats["errors"] += 1
        _log(f"[aicrowd] error: {e}")
        return items


def fetch_drivendata(stats):
    """DrivenData open competitions. Only walk the 'Prize competitions' section
    (active/open); skip 'Practice' and 'Completed' sections."""
    items = []
    try:
        url = "https://www.drivendata.org/competitions/"
        r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            stats["errors"] += 1
            return items
        soup = BeautifulSoup(r.text, "lxml")

        # Find the "Prize competitions" h2 and walk siblings until the next h2.
        # Active prize competitions are the only ones the user can still enter.
        prize_h2 = None
        for h2 in soup.find_all("h2"):
            if "prize competitions" in h2.get_text(strip=True).lower():
                prize_h2 = h2
                break
        if prize_h2 is None:
            return items

        # Collect anchor tags between this h2 and the next h2.
        container = prize_h2.find_parent()
        # Walk forward in document order, stopping at next h2.
        cur = prize_h2
        anchors = []
        while cur is not None:
            cur = cur.find_next()
            if cur is None:
                break
            if getattr(cur, "name", None) == "h2":
                break
            if getattr(cur, "name", None) == "a":
                anchors.append(cur)
            elif hasattr(cur, "find_all"):
                # cur is a tag; collect descendants only if we haven't already.
                pass

        seen = set()
        for a in anchors:
            href = a.get("href") or ""
            if not href.startswith("/competitions/"):
                continue
            if href.endswith("/competitions/") or "/competitions/?" in href:
                continue
            if "/competitions/group/" in href:
                continue
            base = href.split("?")[0]
            if base in seen:
                continue
            seen.add(base)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 4:
                heading = a.find(["h1", "h2", "h3", "h4"])
                title = heading.get_text(strip=True) if heading else title
            if not title:
                continue
            apply_url = urljoin("https://www.drivendata.org", base)
            parent = a.find_parent(["article", "div", "li"])
            card_text = parent.get_text(" ", strip=True) if parent else ""
            # AI filter as safety net.
            if not passes_ai_filter(title + " " + card_text):
                stats["skipped"] += 1
                continue
            items.append(normalize_item(
                title=title[:200],
                apply_url=apply_url,
                platform="DrivenData",
                deadline_iso=_parse_deadline(card_text),
                description=card_text[:300] if card_text else "",
            ))
            stats["ok"] += 1
        return items
    except Exception as e:
        stats["errors"] += 1
        _log(f"[drivendata] error: {e}")
        return items


# ── Accelerators / incubators / acceleration programs ──────────────────────────
# The user wants these alongside coding hackathons (e.g. "IndiaAI Startups Global:
# International Acceleration Programs for Indian AI Startups"). Live accelerator
# sites are JS-heavy / Cloudflare-fronted and unreliable to scrape, so we ship a
# curated set of recurring AI accelerator & acceleration programs with their
# official application pages. Most run rolling / seasonal intakes (deadline=None,
# kept by filter_open). fetch_accelerator_news() adds fresh ones via Google News.
CURATED_ACCELERATORS = [
    # (title, apply_url, region, tags, description, eligibility, benefits)
    ("IndiaAI Startups Global - International Acceleration Programs for Indian AI Startups",
     "https://indiaai.gov.in/", "India",
     ["accelerator", "government", "india", "ai-startups"],
     "MeitY / IndiaAI international acceleration tracks placing Indian AI startups into global programs. Rolling cohorts.",
     "Indian-registered AI startups (DPIIT-recognised).",
     "Placement into international acceleration tracks, plus government backing and global market access."),
    ("Y Combinator (AI startups)", "https://www.ycombinator.com/apply", "Worldwide",
     ["accelerator", "yc", "seed"],
     "Twice-yearly batches; AI-heavy. ~$500k standard deal.",
     "Any early-stage startup with a founding team; pre-launch and idea-stage are welcome.",
     "~$500K on the standard deal, a 3-month program, and the lifelong YC network + Demo Day."),
    ("Antler Residency (AI)", "https://www.antler.co/apply", "Worldwide",
     ["accelerator", "residency", "pre-seed"],
     "Day-zero residency for founders incl. AI; rolling cohorts across 30+ cities.",
     "Solo founders welcome — no company or co-founder needed.",
     "Pre-seed cash, a co-founder matching residency, and hands-on mentorship."),
    ("Techstars AI Accelerators", "https://www.techstars.com/accelerators", "Worldwide",
     ["accelerator", "techstars"],
     "Multiple AI-focused Techstars programs; rolling applications by location.",
     "Early-stage startups; apply to the city/track that fits your team.",
     "Seed investment, a 3-month mentor-driven program, and a global investor network."),
    ("NVIDIA Inception", "https://www.nvidia.com/en-us/startups/", "Worldwide",
     ["incubator", "compute-credits", "gpu"],
     "Free program for AI/ML startups: GPU credits, go-to-market, VC intros. Rolling.",
     "Any AI/ML startup at any stage — free to join.",
     "GPU and cloud credits, go-to-market support, and introductions to VCs."),
    ("Google for Startups AI Accelerator", "https://startup.google.com/programs/accelerator/", "Worldwide",
     ["accelerator", "google", "equity-free"],
     "Equity-free AI accelerator with seasonal cohorts and regional tracks (incl. India).",
     "Seed-to-Series-A AI startups; regional tracks including India.",
     "An equity-free program, Google mentorship, and cloud credits."),
    ("Microsoft for Startups Founders Hub", "https://www.microsoft.com/en-us/startups", "Worldwide",
     ["incubator", "azure-credits"],
     "Azure + OpenAI credits and mentorship for AI startups. Rolling enrollment.",
     "Any early founder; no funding or company stage required.",
     "Free Azure + OpenAI credits and mentorship."),
    ("AI Grant", "https://aigrant.com/", "Worldwide",
     ["grant", "accelerator", "ai-native"],
     "Funding + compute for AI-native startups; seasonal batches.",
     "AI-native startups at a very early stage.",
     "Non-dilutive funding plus compute credits."),
    ("NASSCOM DeepTech Club / AI programs", "https://nasscom.in/", "India",
     ["accelerator", "india", "deeptech"],
     "Indian industry-body acceleration and market-access programs for AI/deeptech startups.",
     "Indian AI / deeptech startups.",
     "Market access, enterprise connects, and acceleration support."),
    ("Startup India - Seed Fund & acceleration", "https://www.startupindia.gov.in/", "India",
     ["government", "india", "grant", "accelerator"],
     "Govt of India seed fund and accelerator partnerships open to AI startups. Rolling.",
     "DPIIT-recognised Indian startups, including AI.",
     "Government seed funding and accelerator partnerships."),
]


def fetch_accelerators(stats):
    """Curated recurring AI accelerator / acceleration programs (always-available)."""
    out = []
    for title, url, region, tags, desc, eligibility, benefits in CURATED_ACCELERATORS:
        item = normalize_item(
            title=title, apply_url=url, platform="Accelerator",
            deadline_iso=None, prize_summary=None, tags=tags,
            description=desc, region=region,
            eligibility=eligibility, benefits=benefits,
        )
        if item:
            out.append(item)
            stats["ok"] += 1
    return out


def fetch_accelerator_news(stats):
    """Surface freshly-announced AI accelerators/acceleration programs via Google
    News RSS so the curated list is topped up with timely, dated opportunities."""
    out = []
    queries = [
        "AI startup accelerator applications open",
        "AI acceleration program for startups deadline",
        "India AI startup accelerator cohort",
    ]
    for q in queries:
        url = "https://news.google.com/rss/search?q=" + requests.utils.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=_headers())
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "xml")
            for it in soup.find_all("item")[:6]:
                title = _strip_html(it.title.text if it.title else "")
                link = it.link.text if it.link else ""
                if not title or not link:
                    continue
                if not passes_ai_filter(title):
                    continue
                deadline = _parse_deadline(title)
                item = normalize_item(
                    title=title, apply_url=link, platform="Accelerator (news)",
                    deadline_iso=deadline, tags=["accelerator", "news"],
                    description=title, region="Worldwide",
                )
                if item:
                    out.append(item)
                    stats["ok"] += 1
        except Exception as e:
            stats["errors"] += 1
            _log(f"[accelerator_news] {q}: {e}")
    return out


# ── Orchestration ─────────────────────────────────────────────────────────────

def _canon_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip().lower()
    # Strip query/fragment.
    u = re.sub(r"[?#].*$", "", u)
    # Trailing slash off.
    if u.endswith("/"):
        u = u[:-1]
    return u


def dedupe(items):
    seen = {}
    out = []
    for it in items:
        key = _canon_url(it.get("apply_url", ""))
        if not key or key in seen:
            continue
        seen[key] = True
        out.append(it)
    return out


def filter_open(items):
    """Drop items with a past deadline. Keep null deadlines (rolling/unknown)."""
    today = date.today().isoformat()
    return [it for it in items if (it.get("deadline_iso") is None or it["deadline_iso"] >= today)]


def sort_by_deadline(items):
    """Ascending by deadline; null last."""
    def key(it):
        d = it.get("deadline_iso")
        return (1, "") if d is None else (0, d)
    return sorted(items, key=key)


SOURCES = [
    ("devpost", fetch_devpost),
    ("kaggle", fetch_kaggle),
    ("huggingface", fetch_huggingface),
    ("mlh", fetch_mlh),
    ("lablab.ai", fetch_lablab),
    ("aicrowd", fetch_aicrowd),
    ("drivendata", fetch_drivendata),
    ("accelerators", fetch_accelerators),
    ("accelerator_news", fetch_accelerator_news),
]


def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    all_items = []
    for name, fn in SOURCES:
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        t0 = time.time()
        try:
            items = fn(stats) or []
        except Exception as e:
            items = []
            stats["errors"] += 1
            _log(f"[{name}] unhandled error: {e}")
        elapsed = time.time() - t0
        _log(f"[{name}] ok={stats['ok']} skipped={stats['skipped']} errors={stats['errors']} ({elapsed:.1f}s)")
        all_items.extend(items)

    deduped = dedupe(all_items)
    open_only = filter_open(deduped)
    sorted_items = sort_by_deadline(open_only)

    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "hackathons": sorted_items,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    _log(f"[total] sources={len(SOURCES)} raw={len(all_items)} deduped={len(deduped)} open={len(open_only)}")
    _log(f"[total] wrote {OUTPUT_FILE}")
    return True


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
