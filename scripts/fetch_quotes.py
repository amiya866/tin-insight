import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
SINA_URL = "https://hq.sinajs.cn/rn=tin-pages&list=nf_SN0,nf_AG0,nf_CU0,hf_SND,s_sh000852"
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (GitHub Actions; Tin Dashboard)",
}
ZHIJI_URL = "https://zhiji-ai.xyz/guan/api/quote"


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct(last, reference):
    if last is None or reference in (None, 0):
        return None
    return (last - reference) / reference * 100


def ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def clock(value):
    text = str(value or "")
    if len(text) == 6 and text.isdigit():
        return f"{text[:2]}:{text[2:4]}:{text[4:]}"
    return text


def fetch_sina_rows():
    request = Request(SINA_URL, headers=SINA_HEADERS)
    with urlopen(request, timeout=30) as response:
        text = response.read().decode("gb18030", errors="replace")
    return {
        key: value.split(",")
        for key, value in re.findall(r'var hq_str_(\w+)="([^"]*)";', text)
    }


def fetch_zhiji_quotes():
    key = os.environ.get("ZHIJI_API_KEY", "").strip()
    if not key:
        return {}
    request = Request(
        ZHIJI_URL + "?" + urlencode({"symbols": "SN,AG,CU", "key": key}),
        headers={"User-Agent": "Tin Dashboard GitHub Actions"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("quotes") or payload.get("data") or []
    result = {}
    for item in rows:
        product = str(item.get("product") or item.get("resolved_from") or "").upper()
        if product and not item.get("error"):
            result[product] = item
    return result


def zhiji_quote(item, fallback_name, now):
    if not item:
        return None
    return {
        "symbol": item.get("symbol"),
        "name": item.get("name") or fallback_name,
        "last": number(item.get("last")),
        "change_pct": number(item.get("change_pct")),
        "time": item.get("time"),
        "date": now.date().isoformat(),
        "open_interest": number(item.get("open_interest")),
        "volume": number(item.get("volume")),
        "source": "实时行情",
    }


def sina_domestic(row, symbol, fallback_name):
    if not row or len(row) < 18:
        return None
    last = number(row[8])
    reference = next(
        (value for value in (number(item) for item in row[18:]) if value and value > 1000),
        number(row[10]),
    )
    return {
        "symbol": symbol,
        "name": row[0] or fallback_name,
        "last": last,
        "change_pct": pct(last, reference),
        "time": clock(row[1]),
        "date": row[17],
        "open_interest": number(row[13]),
        "volume": number(row[14]),
        "source": "新浪期货行情（回退）",
    }


now = datetime.now(SHANGHAI)
rows = fetch_sina_rows()
try:
    zhiji = fetch_zhiji_quotes()
except Exception:
    zhiji = {}

sn = zhiji_quote(zhiji.get("SN"), "沪锡", now) or sina_domestic(rows.get("nf_SN0"), "SN0", "沪锡")
ag = zhiji_quote(zhiji.get("AG"), "沪银", now) or sina_domestic(rows.get("nf_AG0"), "AG0", "沪银")
cu = zhiji_quote(zhiji.get("CU"), "沪铜", now) or sina_domestic(rows.get("nf_CU0"), "CU0", "沪铜")

lme_row = rows.get("hf_SND")
if not lme_row or len(lme_row) < 13:
    raise RuntimeError("Sina LME tin quote response is incomplete")
lme_last = number(lme_row[0])
lme = {
    "symbol": "SND",
    "name": lme_row[13] if len(lme_row) > 13 else "LME锡3个月",
    "last": lme_last,
    "change_pct": pct(lme_last, number(lme_row[7])),
    "time": lme_row[6],
    "date": lme_row[12],
    "source": "新浪外盘期货准实时",
}

csi_row = rows.get("s_sh000852")
csi1000 = {
    "symbol": "000852",
    "name": csi_row[0] if csi_row else "中证1000",
    "last": number(csi_row[1]) if csi_row and len(csi_row) > 1 else None,
    "change_pct": number(csi_row[3]) if csi_row and len(csi_row) > 3 else None,
    "date": now.date().isoformat(),
    "time": now.strftime("%H:%M:%S"),
    "source": "新浪中证1000实时指数",
}

as_of = now.isoformat(timespec="seconds")
payload = {
    "updated_at": as_of,
    "source": "实时行情优先；新浪回退",
    "sn": sn,
    "lme": lme,
    "ag": ag,
    "cu": cu,
    "csi1000": csi1000,
    "ratios": {
        "tin_silver": {
            "value": ratio(sn and sn.get("last"), ag and ag.get("last")),
            "as_of": as_of,
            "source": "实时行情",
        },
        "tin_copper": {
            "value": ratio(sn and sn.get("last"), cu and cu.get("last")),
            "as_of": as_of,
            "source": "实时行情",
        },
        "tin_csi1000": {
            "value": ratio(sn and sn.get("last"), csi1000.get("last")),
            "as_of": as_of,
            "source": "实时行情 / 新浪中证1000",
        },
    },
}
Path("quotes.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps(payload, ensure_ascii=False))
