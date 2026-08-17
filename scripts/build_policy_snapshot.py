# -*- coding: utf-8 -*-
"""Build a static policy snapshot (policy.json) for the tin dashboard.
Fallback layer when the live Worker (/api/policy) is unreachable from mainland networks.
Fetches Fed press releases + speeches RSS + a tin-industry Google News query.

Usage: python scripts/build_policy_snapshot.py
Output: policy.json (same item shape as the Worker /api/policy)
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

SHANGHAI = timezone(timedelta(hours=8))
OUT = __import__("pathlib").Path(__file__).resolve().parent.parent / "policy.json"

FED_PRESS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
FED_SPEECH_URL = "https://www.federalreserve.gov/feeds/speeches_and_testimony.xml"
GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?q="
    + urllib.parse.quote("(tin OR 锡) (mine OR smelter OR 出口 OR supply)") if False else None
)
import urllib.parse
GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q=" + urllib.parse.quote(
    "tin 锡 mine OR smelter OR supply OR export"
)

FED_FILTER = re.compile(
    r"monetary|federal funds|interest rate|inflation|economic|industrial production|fomc|tariff|rate decision|projections", re.I
)


def fetch_rss(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def parse_rss(xml_text: str) -> list[dict]:
    """Very small RSS parser: pull <item> blocks and their title/link/pubDate."""
    items = []
    for block in re.findall(r"<item>(.*?)</item>", xml_text, re.S):
        def field(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S)
            return m.group(1).strip() if m else ""
        title = re.sub(r"<[^>]+>", "", field("title")).strip()
        link = re.search(r"<link[^>]*>(.*?)</link>", block, re.S)
        link = link.group(1).strip() if link else ""
        pub = field("pubDate")
        if not title:
            continue
        items.append({"title": title, "url": link, "date": pub})
    return items


def normalize_date(raw: str) -> str:
    """RFC822 → YYYY-MM-DD (Shanghai)."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SHANGHAI).strftime("%Y-%m-%d")
    except Exception:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw or "")
        return m.group(0) if m else (raw or "")[:10]


def category_of(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"fed|fomc|interest rate|inflation|cpi|tariff", t):
        return "宏观政策 · 美联储"
    if re.search(r"tin|锡|mine|smelter|export|supply", t):
        return "锡产业动态"
    return "政策与事件"


def build() -> dict:
    errors: dict[str, str] = {}
    items: list[dict] = []

    for label, url in (("美联储新闻发布", FED_PRESS_URL), ("美联储讲话证词", FED_SPEECH_URL), ("锡产业聚合", GOOGLE_NEWS_URL)):
        try:
            blocks = parse_rss(fetch_rss(url))
            filtered = blocks
            if label.startswith("美联储"):
                filtered = [b for b in blocks if FED_FILTER.search(b["title"])]
            for b in filtered:
                cat = category_of(b["title"])
                items.append({
                    "category": cat,
                    "title": b["title"],
                    "title_zh": (("美联储｜" if cat == "宏观政策 · 美联储" else "锡产业｜") if cat == "宏观政策 · 美联储" else "锡产业｜") + b["title"] if False else b["title"],
                    "summary_zh": "官方渠道发布" + ("，" + b["title"] if len(b["title"]) > 0 else "") + "。原文链接已保留供核验。",
                    "date": normalize_date(b["date"]),
                    "source": label,
                    "official": label.startswith("美联储"),
                    "url": b["url"],
                })
        except Exception as e:  # noqa: BLE001
            errors[label] = str(e)[:200]

    # 去重
    seen, dedup = set(), []
    for it in items:
        key = (it["date"], it["title"][:40])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    # 官方优先 + 日期新在前
    dedup.sort(key=lambda x: (0 if x["official"] else 1, x["date"]), reverse=True)
    dedup = dedup[:12]

    payload = {
        "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "source": "美联储官方 RSS + Google News 锡产业聚合 · GitHub Actions 静态快照（Worker 不可达时的回退层）",
        "items": dedup,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "ok": bool(dedup),
        "updated_at": payload["updated_at"],
        "items": len(dedup),
        "categories": sorted({i["category"] for i in dedup}),
        "dates": [i["date"] for i in dedup][:5],
        "errors": errors,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    build()
