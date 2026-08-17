# -*- coding: utf-8 -*-
"""Build a recent, Chinese-only policy/event fallback for the tin dashboard."""
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SHANGHAI = timezone(timedelta(hours=8))
OUT = Path(__file__).resolve().parent.parent / "policy.json"
WORKER_URL = "https://tin-insight-api.wangziquan-tin.workers.dev/api/policy?static=1"
LOOKBACK_DAYS = 45
MAX_ITEMS = 7
MAX_MACRO_ITEMS = 1

CURATED_ITEMS = [
    {
        "category": "秘鲁锡供应",
        "title": "Minsur二季度精锡产量保持平稳，检修导致环比回落",
        "title_zh": "Minsur二季度精锡产量保持平稳，检修导致环比回落",
        "summary_zh": "Minsur二季度精锡产量为7,000吨，同比仅下降0.5%，但受检修影响环比下降15.4%；供应没有失速，季度环比回落主要是计划性检修。",
        "date": "2026-08-05",
        "source": "国际锡业协会",
        "official": True,
        "url": "https://www.internationaltin.org/minsur-invests-in-the-future-as-q2-output-holds-steady/",
    },
    {
        "category": "国内锡供应",
        "title": "银漫矿业采选系统全面停产，复产时间仍未确定",
        "title_zh": "银漫矿业采选系统全面停产，复产时间仍未确定",
        "summary_zh": "兴业银锡公告显示，银漫矿业在井下事故后先停采，7月30日选矿和尾矿系统同步停产；复产需完成事故调查及安监验收，持续时间尚不确定。",
        "date": "2026-07-31",
        "source": "兴业银锡公告",
        "official": True,
        "url": "http://www.cninfo.com.cn/new/disclosure/stock?stockCode=000426",
    },
    {
        "category": "宏观政策",
        "title": "美联储7月议息会议维持目标利率区间不变",
        "title_zh": "美联储7月议息会议维持目标利率区间不变",
        "summary_zh": "美联储公开市场委员会以9比3通过声明，维持目标利率区间不变。该项只作为美元与风险偏好的宏观背景，不替代锡自身供需判断。",
        "date": "2026-07-29",
        "source": "美联储",
        "official": True,
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
    },
    {
        "category": "印尼锡供应",
        "title": "PT Timah二季度精锡产量环比下降7%，换证延迟仍在扰动供应",
        "title_zh": "PT Timah二季度精锡产量环比下降7%，换证延迟仍在扰动供应",
        "summary_zh": "PT Timah二季度精锡产量5,235吨，环比下降7.0%、同比增长38.7%；矿产锡5,920吨，同比增长30.5%。季度减量主要来自重新许可流程延迟。",
        "date": "2026-07-29",
        "source": "国际锡业协会 / PT Timah",
        "official": True,
        "url": "https://www.internationaltin.org/pt-timah-weathers-q2-regulatory-turbulence/",
    },
    {
        "category": "澳大利亚锡供应",
        "title": "Renison二季度产量回落，品位、设备与回收率共同拖累",
        "title_zh": "Renison二季度产量回落，品位、设备与回收率共同拖累",
        "summary_zh": "Metals X披露Renison二季度产量较一季度下降，主要受入选品位降低、设备可用率问题和回收率下降影响；现阶段属于运营扰动，需跟踪后续修复。",
        "date": "2026-07-27",
        "source": "国际锡业协会 / Metals X",
        "official": True,
        "url": "https://www.internationaltin.org/renison-production-slips-in-q2/",
    },
    {
        "category": "刚果（金）锡供应",
        "title": "Alphamin二季度收益创新高，Bisie高产状态延续",
        "title_zh": "Alphamin二季度收益创新高，Bisie高产状态延续",
        "summary_zh": "Alphamin二季度EBITDA为1.67亿美元，环比增长6%；锡价上涨和销量稳定提供支撑。Bisie二季度产锡5,013吨，供应增量仍在兑现。",
        "date": "2026-07-20",
        "source": "国际锡业协会 / Alphamin",
        "official": True,
        "url": "https://www.internationaltin.org/alphamin-reports-record-q2-earnings-on-elevated-tin-prices/",
    },
]


def fetch_worker():
    request = urllib.request.Request(WORKER_URL, headers={"User-Agent": "Tin Insight Static Policy/2.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def category_zh(value):
    text = str(value or "").upper()
    if "MACRO" in text or "宏观" in text:
        return "宏观政策"
    if "MYANMAR" in text or "缅甸" in text:
        return "缅甸锡供应"
    if "INDONESIA" in text or "印尼" in text:
        return "印尼锡供应"
    if "DRC" in text or "CONGO" in text or "刚果" in text:
        return "刚果（金）锡供应"
    if "AI" in text or "ELECTRON" in text or "下游" in text:
        return "电子与下游需求"
    if "SUPPLY" in text or "供应" in text:
        return "锡供应"
    return "锡产业动态"


def enough_chinese(value, minimum):
    text = str(value or "")
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return chinese >= minimum and chinese >= latin * 0.25


def normalize_worker_item(item, cutoff):
    raw_date = str(item.get("date") or "")[:10]
    try:
        event_date = date.fromisoformat(raw_date)
    except ValueError:
        return None
    title = str(item.get("title_zh") or "").strip()
    summary = str(item.get("summary_zh") or "").strip()
    if event_date < cutoff or not enough_chinese(title, 6) or not enough_chinese(summary, 20):
        return None
    url = str(item.get("url") or "").strip()
    if url.startswith("<![CDATA[") and url.endswith("]]>"):
        url = url[9:-3].strip()
    return {
        "category": category_zh(item.get("category")),
        "title": title,
        "title_zh": title,
        "summary_zh": summary,
        "date": raw_date,
        "source": str(item.get("source") or "公开来源"),
        "official": bool(item.get("official")),
        "url": url,
        "_curated": False,
    }


def relevance_score(item):
    text = f'{item.get("title_zh", "")} {item.get("summary_zh", "")}'
    if item.get("_curated"):
        return 10
    if re.search(r"实习生|路线图|团聚技术|会议报名|招聘", text):
        return -1
    if re.search(r"停产|复产|产量|减产|出口|进口|换证|许可|事故|库存|议息|利率", text):
        return 6
    if re.search(r"矿山|冶炼|供应|焊料|半导体|电池|需求", text):
        return 3
    return 0


def dedupe_and_rank(items):
    seen = set()
    ranked = []
    macro_count = 0
    items.sort(key=lambda item: (relevance_score(item), item["date"]), reverse=True)
    for item in items:
        if relevance_score(item) < 0:
            continue
        key = (item.get("url") or "").split("?", 1)[0] or re.sub(r"\s+", "", item["title_zh"])
        if not key or key in seen:
            continue
        if item["category"] == "宏观政策":
            if macro_count >= MAX_MACRO_ITEMS:
                continue
            macro_count += 1
        seen.add(key)
        ranked.append({key: value for key, value in item.items() if not key.startswith("_")})
        if len(ranked) >= MAX_ITEMS:
            break
    return ranked


def build():
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    items = []
    errors = {}
    try:
        payload = fetch_worker()
        for raw in payload.get("items") or []:
            clean = normalize_worker_item(raw, cutoff)
            if clean:
                items.append(clean)
    except Exception as error:
        errors["实时中文事件源"] = str(error)[:200]
    items.extend(
        {**item, "_curated": True}
        for item in CURATED_ITEMS
        if date.fromisoformat(item["date"]) >= cutoff
    )
    items = dedupe_and_rank(items)
    payload = {
        "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "source": "实时中文事件源 + 国际锡业协会/公司公告核验；仅保留近45天，宏观最多1条",
        "method": "锡产业优先；中文标题与中文事实摘要不合格的记录拒绝覆盖；最多7条",
        "items": items,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "ok": bool(items),
        "updated_at": payload["updated_at"],
        "items": len(items),
        "oldest": min((item["date"] for item in items), default=None),
        "categories": sorted({item["category"] for item in items}),
        "errors": errors,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
