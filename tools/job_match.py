"""
Profile-aware job ranking. Reads .tmp/jobs.json + workflows/user_profile.md
and writes .tmp/jobs_ranked.json with each surviving job annotated with
its matched skills, target-role bonus, and final score.

Hard exclusions (seniority, geo lock, tech mismatch) drop a job entirely.
Skill weights, target-role keywords, and exclusion tokens all come from
workflows/user_profile.md so the user can retune matching without code
edits.

Usage:
    python -m tools.job_match            # reads jobs.json -> writes jobs_ranked.json
    from tools.job_match import run; run()
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from tools._text_match import extract_skill_hits, tokenize_words

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
PROFILE_FILE = os.path.join(PROJECT_ROOT, "workflows", "user_profile.md")
JOBS_INPUT = os.path.join(TMP_DIR, "jobs.json")
JOBS_OUTPUT = os.path.join(TMP_DIR, "jobs_ranked.json")

TARGET_ROLE_BONUS = 4          # additive bonus if any target-role keyword hits the title
TOP_N = 25                     # cap surfaced to PDF (matches old JOB_CAP)


def _parse_profile_md(text: str) -> dict:
    """Light parser: bullet lists under H2 sections become the section value."""
    sections: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
            continue
        if current is None:
            continue
        m = re.match(r"^\s*-\s+(.*)$", line)
        if m:
            sections[current].append(m.group(1).strip())
    return sections


def _expand_skill_lines(lines: list[str]) -> dict[str, int]:
    """Turn 'Weight N - skill1, skill2, ...' lines into a {skill: weight} dict."""
    weighted: dict[str, int] = {}
    for line in lines:
        m = re.match(r"weight\s+(\d+)\s*[:\-—]\s*(.*)$", line, re.IGNORECASE)
        if not m:
            continue
        try:
            w = int(m.group(1))
        except ValueError:
            continue
        for item in m.group(2).split(","):
            term = item.strip().rstrip(".").lower()
            if not term:
                continue
            existing = weighted.get(term, 0)
            if w > existing:
                weighted[term] = w
    return weighted


def _find_section(raw: dict, *prefixes: str) -> list[str]:
    """Return bullet lines for the first H2 whose lowercased title starts with
    any of `prefixes`. Tolerant of the user editing the heading suffix."""
    for key, lines in raw.items():
        if any(key.startswith(p) for p in prefixes):
            return lines
    return []


def load_profile(profile_path: str = PROFILE_FILE) -> dict:
    """Load workflows/user_profile.md into a structured dict.

    Expected bullet format under each H2:
      Target roles  -> `- AI Automation Engineer (...)`
      Skills        -> `- Weight 3: n8n, voiceflow, ...`
      Exclusions    -> `- Seniority: senior, sr., lead, ...`
                       `- Geo: us only, eu only, ...`
                       `- Tech: data scientist, mlops, ...`
    """
    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"Profile not found: {profile_path}")
    with open(profile_path, "r", encoding="utf-8") as f:
        text = f.read()
    raw = _parse_profile_md(text)

    target_roles = [s.lower() for s in _find_section(raw, "target roles")]
    skills_weighted = _expand_skill_lines(_find_section(raw, "skills"))

    excl_seniority: list[str] = []
    excl_geo: list[str] = []
    excl_tech: list[str] = []
    for line in _find_section(raw, "hard exclusions", "exclusions"):
        if ":" not in line:
            continue
        label, _, rest = line.partition(":")
        label_l = label.strip().lower()
        tokens = [t.strip().rstrip(".").lower() for t in rest.split(",") if t.strip()]
        if "senior" in label_l:
            excl_seniority += tokens
        elif "geo" in label_l:
            excl_geo += tokens
        elif "tech" in label_l:
            excl_tech += tokens

    return {
        "target_roles": target_roles,
        "target_role_keywords": _role_keywords(target_roles),
        "skills_weighted": skills_weighted,
        "excl_seniority": excl_seniority,
        "excl_geo": excl_geo,
        "excl_tech": excl_tech,
    }


def _role_keywords(role_lines: list[str]) -> set[str]:
    """Reduce target roles to compact keywords for title-match bonus.

    Strips parenthetical seniority hints ('Junior / Entry / Mid'), splits on
    slashes, lowercases. Single-word noise tokens dropped. Multi-word phrases
    kept verbatim for substring matching.
    """
    kws: set[str] = set()
    NOISE = {"engineer", "developer", "specialist", "consultant", "ai"}
    for raw in role_lines:
        # Drop parenthetical hints
        s = re.sub(r"\([^)]*\)", "", raw).strip().lower()
        for part in s.split("/"):
            term = part.strip()
            if not term:
                continue
            # Keep multi-word phrases as-is for substring match.
            if " " in term:
                # Strip leading "ai " for breadth: 'ai automation' -> 'automation'.
                kws.add(term)
                if term.startswith("ai ") and len(term) > 4:
                    kws.add(term[3:])
            elif term not in NOISE:
                kws.add(term)
    return kws


def score_job(job: dict, profile: dict) -> dict:
    """Return a scoring record. Caller decides whether to drop dropped=True jobs."""
    title = (job.get("title") or "").lower()
    summary = (job.get("summary") or "").lower()
    location = (job.get("location") or "").lower()
    company = (job.get("company") or "").lower()
    blob = " ".join([title, summary, location, company])
    tokens = tokenize_words(blob)

    # Hard exclusions — seniority lives in title; geo lives in location/summary;
    # tech mismatch lives in title.
    for tok in profile["excl_seniority"]:
        if " " in tok or "-" in tok or "." in tok:
            if tok in title:
                return {"dropped": True, "drop_reason": f"seniority:{tok}", "score": 0, "matched_skills": [], "title_role_hit": None}
        else:
            if tok in tokens:
                return {"dropped": True, "drop_reason": f"seniority:{tok}", "score": 0, "matched_skills": [], "title_role_hit": None}

    geo_blob = f"{location} {summary}".lower()
    for tok in profile["excl_geo"]:
        if tok in geo_blob:
            return {"dropped": True, "drop_reason": f"geo:{tok}", "score": 0, "matched_skills": [], "title_role_hit": None}

    for tok in profile["excl_tech"]:
        if " " in tok or "-" in tok or "." in tok:
            if tok in title:
                return {"dropped": True, "drop_reason": f"tech:{tok}", "score": 0, "matched_skills": [], "title_role_hit": None}
        else:
            if tok in tokens:
                return {"dropped": True, "drop_reason": f"tech:{tok}", "score": 0, "matched_skills": [], "title_role_hit": None}

    matched, skill_score = extract_skill_hits(blob, profile["skills_weighted"])

    title_role_hit = None
    for kw in profile["target_role_keywords"]:
        if " " in kw:
            if kw in title:
                title_role_hit = kw
                break
        elif kw in tokens:
            title_role_hit = kw
            break

    total = skill_score + (TARGET_ROLE_BONUS if title_role_hit else 0)
    return {
        "dropped": False,
        "drop_reason": None,
        "score": total,
        "matched_skills": matched,
        "title_role_hit": title_role_hit,
    }


def _recency_key(j: dict) -> str:
    """Sort key: most recent first. Posted strings are best-effort."""
    return (j.get("posted") or "")


def rank_jobs(jobs: list[dict], profile: dict, top_n: int = TOP_N) -> list[dict]:
    """Rank, drop excluded jobs, attach metadata, cap at top_n."""
    enriched = []
    for j in jobs:
        rec = score_job(j, profile)
        if rec["dropped"]:
            continue
        out = dict(j)
        out["_score"] = rec["score"]
        out["matched_skills"] = rec["matched_skills"]
        out["title_role_hit"] = rec["title_role_hit"]
        out["strong_match"] = rec["title_role_hit"] is not None and len(rec["matched_skills"]) >= 1
        enriched.append(out)

    # Newest first within equal score: stable sort by recency desc, then score desc.
    enriched.sort(key=_recency_key, reverse=True)
    enriched.sort(key=lambda j: -j["_score"])
    return enriched[:top_n]


def run() -> bool:
    if not os.path.exists(JOBS_INPUT):
        print(f"[job_match] no input at {JOBS_INPUT} - run scrape_jobs first")
        return False
    with open(JOBS_INPUT, "r", encoding="utf-8") as f:
        payload = json.load(f)
    jobs = payload.get("jobs", []) or []

    profile = load_profile()
    ranked = rank_jobs(jobs, profile)

    out = {
        "ranked_at": datetime.now(timezone.utc).isoformat(),
        "profile_path": os.path.relpath(PROFILE_FILE, PROJECT_ROOT),
        "input_count": len(jobs),
        "ranked_count": len(ranked),
        "target_roles": profile["target_roles"],
        "jobs": ranked,
    }
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(JOBS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # Record the roles actually surfaced today so the next run can rotate them out.
    try:
        from tools.job_history import record_shown
        record_shown([j.get("url") for j in ranked])
    except Exception as e:
        print(f"[job_match] could not record shown-job history: {e}")

    print(f"[job_match] {len(jobs)} input -> {len(ranked)} ranked (top {TOP_N}) -> {JOBS_OUTPUT}")
    return True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
