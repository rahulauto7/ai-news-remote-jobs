"""One-shot recovery: re-route articles into specified under-filled sections.

Reuses the DeepSeek client + prompts from tools.deepseek_analyze. Filters the
RSS pool to articles NOT already placed in analyzed_content.json, sends them
through the model with a focused instruction set, and merges the resulting
items into the target sections in-place.

Usage:
    python -m tools.recover_empty_sections quantum_ai_research ai_self_improvement_rsi
"""
from __future__ import annotations

import json
import os
import sys
from typing import Iterable

from tools.deepseek_analyze import (
    ARTICLE_BODY_CHARS,
    DEEPSEEK_MODEL,
    SECTIONS_BRIEF,
    SYSTEM_PROMPT,
    build_articles_payload,
    call_deepseek,
    parse_dt,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
RSS_PATH = os.path.join(TMP_DIR, "rss_articles.json")
ANALYZED_PATH = os.path.join(TMP_DIR, "analyzed_content.json")

CHUNK_SIZE = 40
SECTION_CAP = 8


def load_pool(targets: set[str]) -> list[dict]:
    rss = json.load(open(RSS_PATH))
    articles = rss.get("articles", []) if isinstance(rss, dict) else rss
    analyzed = json.load(open(ANALYZED_PATH))
    placed_urls = {
        it.get("url")
        for sec in analyzed["sections"].values()
        for it in sec
        if it.get("url")
    }
    pool = [a for a in articles if a.get("url") and a["url"] not in placed_urls]
    pool.sort(key=lambda a: parse_dt(a.get("published", "")), reverse=True)
    return pool


def chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def main(targets: list[str]) -> None:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
        api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY missing", file=sys.stderr)
        sys.exit(1)

    target_set = set(targets)
    pool = load_pool(target_set)
    print(f"[recover] pool size: {len(pool)} unrouted articles; targets={targets}")
    print(f"[recover] model={DEEPSEEK_MODEL}")

    found: dict[str, list[dict]] = {t: [] for t in targets}
    seen_urls: set[str] = set()

    import tools.deepseek_analyze as dsa
    original_user_msg_suffix = (
        f"\n\nIMPORTANT: This is a RECOVERY pass. Only return articles that fit one of these sections: {targets}. "
        "Skip everything else. Apply the same strict criteria as a normal pass. "
        "If you cannot find any article matching these sections in this batch, return {\"items\": []}."
    )

    def call_focused(payload):
        user_msg = (
            SECTIONS_BRIEF
            + "\nArticles to categorise (JSON list). Use the integer `i` as the article id.\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n\nReturn JSON: {\"items\": [{\"i\": <int>, \"section\": \"<key>\", "
              "\"summary\": \"<1-2 sentences>\", \"relevance\": <1-5>}]}. "
              "Omit any article that does not fit a section."
            + original_user_msg_suffix
        )
        body = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 16000,
        }
        import requests
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        r = requests.post(dsa.DEEPSEEK_URL, headers=headers, json=body, timeout=180)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        usage = data.get("usage", {})
        finish = data["choices"][0].get("finish_reason")
        return parsed.get("items", []), usage, finish

    for ci, batch in enumerate(chunks(pool, CHUNK_SIZE), start=1):
        payload = build_articles_payload(batch)
        try:
            items, usage, finish = call_focused(payload)
        except Exception as e:
            print(f"  chunk {ci}: ERROR {e}")
            continue
        kept = 0
        for it in items:
            sec = it.get("section")
            i = it.get("i")
            if sec not in target_set or not isinstance(i, int) or i < 0 or i >= len(batch):
                continue
            src = batch[i]
            url = src.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            found[sec].append({
                "title": src.get("title", ""),
                "url": url,
                "source": src.get("source", ""),
                "summary": it.get("summary", "") or src.get("summary", ""),
                "published": src.get("published", ""),
                "relevance": int(it.get("relevance", 3)) if str(it.get("relevance", "")).isdigit() else 3,
            })
            kept += 1
        print(
            f"  chunk {ci}: in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} "
            f"finish={finish} kept={kept}"
        )

    analyzed = json.load(open(ANALYZED_PATH))
    for t in targets:
        items = found[t]
        items.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        items = items[:SECTION_CAP]
        analyzed["sections"][t] = items
        print(f"[recover] {t}: {len(items)} items merged")
    with open(ANALYZED_PATH, "w") as f:
        json.dump(analyzed, f, indent=2)
    print(f"[recover] wrote {ANALYZED_PATH}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["quantum_ai_research", "ai_self_improvement_rsi"]
    main(args)
